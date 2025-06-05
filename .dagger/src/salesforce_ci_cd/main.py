import random
from typing import Annotated

import dagger
from dagger import DefaultPath, Doc, dag, function, object_type


@object_type
class SalesforceCiCd:
    @function
    def build_env(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
    ) -> dagger.Container:
        """Build a ready-to-use development environment"""

        # Create cache volumes for better performance
        node_cache = dag.cache_volume("node")
        apt_cache = dag.cache_volume("apt")

        return (
            dag.container()
            # Start with ubuntu-latest
            .from_("ubuntu:latest")
            .with_mounted_cache("/var/cache/apt", apt_cache)
            .with_directory("/src", source)
            .with_workdir("/src")
            # Update package list
            .with_exec(["apt-get", "update"])
            # Install basic dependencies
            .with_exec(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "curl",
                    "wget",
                    "gnupg",
                    "software-properties-common",
                    "unzip",
                ]
            )
            # Install git if not already present
            .with_exec(["apt-get", "install", "-y", "git"])
            # Install Node.js
            .with_exec(
                [
                    "curl",
                    "-fsSL",
                    "https://deb.nodesource.com/setup_22.x",
                    "-o",
                    "nodesource_setup.sh",
                ]
            )
            .with_exec(["bash", "nodesource_setup.sh"])
            .with_exec(["apt-get", "install", "-y", "nodejs"])
            # Install Java (OpenJDK 17)
            .with_exec(["apt-get", "install", "-y", "openjdk-17-jdk"])
            # Install Salesforce CLI
            .with_exec(["npm", "install", "-g", "@salesforce/cli"])
            # Create a file called unsignedPluginAllowList.json and put it in one of these directories: (ubunut): $HOME/.config/sf
            # Add the names of the plugins you trust to the JSON file as an array in a simple array of strings. For example:["sfdx-git-delta",]
            .with_exec(["mkdir", "-p", "/root/.config/sf"])
            .with_exec(
                [
                    "bash",
                    "-c",
                    'echo \'["sfdx-git-delta", "@salesforce/sfdx-scanner"]\' > /root/.config/sf/unsignedPluginAllowList.json',
                ]
            )
            # Install SFDX Git Delta
            .with_exec(["sf", "plugins", "install", "sfdx-git-delta"])
            # Install SFDX Scanner
            .with_exec(
                [
                    "sf",
                    "plugins",
                    "install",
                    "@salesforce/sfdx-scanner",
                ]
            )
            # Mount node cache and install project dependencies
            .with_mounted_cache("/root/.npm", node_cache)
            .with_exec(["npm", "install"])
            # Clean up
            .with_exec(["apt-get", "clean"])
            .with_exec(["rm", "-rf", "/var/lib/apt/lists/*", "nodesource_setup.sh"])
        )

    @function
    async def prepare_delta_source(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        container: dagger.Container | None = None,
        source_dir: Annotated[str, Doc("Source directory path")] = "force-app/",
        output_dir: Annotated[
            str, Doc("Output directory for delta packages")
        ] = "changed-sources",
    ) -> dagger.Container:
        """Prepare delta sources for more efficient deployments."""

        if container is None:
            container = await self.build_env(source)

        return (
            container.with_exec(["mkdir", "-p", output_dir]).with_exec(
                [
                    "sf",
                    "sgd",
                    "source",
                    "delta",
                    "--to",
                    "HEAD",
                    "--from",
                    "HEAD^",
                    "--output-dir",
                    f"{output_dir}/",
                    "--generate-delta",
                    "--source-dir",
                    source_dir,
                ]
            )
            # List generated delta files for verification
            .with_exec(["ls", "-la", output_dir])
        )

    @function
    async def scan_delta_source(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        container: dagger.Container | None = None,
        output_dir: Annotated[str, Doc("Delta sources directory")] = "changed-sources",
    ) -> dagger.Container:
        """Scan delta sources for code quality issues using Salesforce Scanner."""

        if container is None:
            container = await self.prepare_delta_source(source)

        return (
            container
            # Verify output_dir exists and has files
            .with_exec(
                [
                    "bash",
                    "-c",
                    f"""
                if [ ! -d "/src/{output_dir}" ]; then
                    echo "Error: Output directory '/src/{output_dir}' does not exist."
                    echo "Please inject container from prepare-delta-source function or ensure delta sources are prepared."
                    exit 1
                fi
                
                if [ -z "$(ls -A /src/{output_dir} 2>/dev/null)" ]; then
                    echo "Error: Output directory '/src/{output_dir}' is empty."
                    echo "Please inject container from prepare-delta-source function or ensure delta sources are prepared."
                    exit 1
                fi
                
                echo "Delta sources directory verified: /src/{output_dir}"
                ls -la /src/{output_dir}
                """,
                ]
            )
            # Change to the delta sources directory
            .with_workdir(f"/src/{output_dir}").with_exec(
                [
                    "bash",
                    "-c",
                    """
                if find . -name "*.cls" -type f | grep -q .; then
                    echo "Found Apex classes, running scanner..."
                    sf scanner run --format sarif --target . --category Design --category "Best Practices" --category Performance --outfile apexScanResults.sarif --engine pmd
                else
                    echo "No Apex classes found to scan, creating empty SARIF file"
                    echo '{"version":"2.1.0","$schema":"https://json.schemastore.org/sarif-2.1.0.json","runs":[{"tool":{"driver":{"name":"Salesforce Code Analyzer","version":"5.0.0"}},"results":[]}}' > apexScanResults.sarif
                fi
                """,
                ]
            )
            # Verify the SARIF file was created
            .with_exec(["ls", "-la", "apexScanResults.sarif"])
            # Return to the original working directory
            .with_workdir("/src")
            # Display scan results summary
            .with_exec(["cat", f"{output_dir}/apexScanResults.sarif"])
        )

    @function
    async def run_lwc_unit_tests(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        container: dagger.Container | None = None,
    ) -> dagger.Container:
        """Run Lightning Web Component unit tests with Jest."""

        if container is None:
            container = await self.build_env(source)

        return (
            container
            # Check if Jest configuration exists
            .with_exec(
                [
                    "bash",
                    "-c",
                    """
                if [ -f "jest.config.js" ] || [ -f "package.json" ]; then
                    echo "Jest configuration found, proceeding with tests..."
                else
                    echo "No Jest configuration found, skipping LWC tests"
                    exit 0
                fi
                """,
                ]
            ).with_exec(  # Run LWC unit tests
                ["npm", "run", "test:unit"]
            )
            # Generate test coverage report
            .with_exec(["npm", "run", "test:unit:coverage"])
            # Display test results summary
            .with_exec(["ls", "-la", "coverage/"])
            # Show coverage summary if available
            .with_exec(
                [
                    "bash",
                    "-c",
                    """
                if [ -f "coverage/lcov-report/index.html" ]; then
                    echo "Coverage report generated at coverage/lcov-report/index.html"
                fi
                if [ -f "coverage/coverage-summary.json" ]; then
                    echo "Coverage Summary:"
                    cat coverage/coverage-summary.json
                fi
                """,
                ]
            )
        )

    @function
    async def login_sf_cli(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        auth_url: Annotated[dagger.Secret, Doc("Salesforce auth URL for login")],
        container: dagger.Container | None = None,
        alias: Annotated[str, Doc("Alias for the org")] = "target-org",
    ) -> dagger.Container:
        """Login to Salesforce CLI using auth URL."""

        if container is None:
            container = await self.build_env(source)

        return (
            container
            # Login using auth URL
            .with_secret_variable("SF_AUTH_URL", auth_url).with_exec(
                [
                    "bash",
                    "-c",
                    f'echo "$SF_AUTH_URL" | sf org login sfdx-url --sfdx-url-stdin --set-default --alias {alias}',
                ]
            )
            # Verify login was successful
            .with_exec(["sf", "org", "display", "--target-org", alias])
            # List available orgs
            .with_exec(["sf", "org", "list"])
        )

    @function
    async def dry_run_delta_changes(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        container: dagger.Container | None = None,
        alias: Annotated[str, Doc("Alias for the org")] = "target-org",
        apex_tests: Annotated[str, Doc("Comma seperated apex test classes")] = "all",
    ) -> dagger.Container:

        return container

    @function
    async def dry_run_delta_destructive_changes(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        container: dagger.Container | None = None,
        alias: Annotated[str, Doc("Alias for the org")] = "target-org",
    ) -> dagger.Container:

        return container

    @function
    async def ci_pipeline(self, source: dagger.Directory) -> str:
        return "ci pipleline"
