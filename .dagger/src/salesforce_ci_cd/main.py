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
        lwc_tests: Annotated[str, Doc("run delta or all lwc tests")] = "all",
        delta_source: Annotated[
            str, Doc("Delta sources directory")
        ] = "changed-sources",
    ) -> dagger.Container:
        """Run Lightning Web Component unit tests with Jest."""

        if container is None:
            container = await self.prepare_delta_source(source)

        if lwc_tests.lower() == "delta":
            container = (
                container
                # Verify delta sources exist
                .with_exec(
                    [
                        "bash",
                        "-c",
                        f"""
                    if [ ! -d "/src/{delta_source}" ]; then
                        echo "Error: Delta sources directory '/src/{delta_source}' does not exist."
                        echo "Please run prepare-delta-source function first."
                        exit 1
                    fi
                    
                    echo "Delta sources directory verified: /src/{delta_source}"
                    ls -la /src/{delta_source}
                    """,
                    ]
                )
                # Check if Jest configuration exists and if there are LWC components to test
                .with_exec(
                    [
                        "bash",
                        "-c",
                        f"""
                    if [ ! -f "jest.config.js" ] && [ ! -f "package.json" ]; then
                        echo "No Jest configuration found, skipping LWC tests"
                        exit 0
                    fi
                    
                    # Check if there are any LWC components in the delta sources
                    if [ ! -d "/src/{delta_source}/force-app/main/default/lwc" ]; then
                        echo "No LWC components found in delta sources. Skipping LWC unit tests."
                        exit 0
                    fi
                    
                    # Count LWC components with tests
                    lwc_count=$(find /src/{delta_source}/force-app/main/default/lwc -name "*.js" -not -path "*/__tests__/*" | wc -l)
                    test_count=$(find /src/{delta_source}/force-app/main/default/lwc -name "*.test.js" | wc -l)
                    
                    echo "Found $lwc_count LWC components and $test_count test files in delta sources"
                    
                    if [ "$test_count" -eq 0 ]; then
                        echo "No LWC test files found in delta sources. Skipping tests."
                        exit 0
                    fi
                    
                    echo "Proceeding with LWC unit tests for delta changes..."
                    """,
                    ]
                )
                # Create a custom Jest configuration for delta testing
                .with_exec(
                    [
                        "bash",
                        "-c",
                        f"""
                    # Create temporary Jest config for delta testing
                    cat > jest.config.delta.js << 'EOF'
                    const {{ jestConfig }} = require('@salesforce/sfdx-lwc-jest/config');

                    module.exports = {{
                        ...jestConfig,
                        testMatch: [
                            '**/{delta_source}/**/lwc/**/__tests__/**/*.test.js'
                        ],
                        collectCoverageFrom: [
                            '**/{delta_source}/**/lwc/**/*.js',
                            '!**/{delta_source}/**/lwc/**/__tests__/**',
                            '!**/{delta_source}/**/lwc/**/__mocks__/**'
                        ],
                        coverageDirectory: 'coverage-delta',
                        coverageReporters: ['text', 'lcov', 'json-summary']
                    }};
                    EOF
                    
                    echo "Custom Jest configuration created for delta testing"
                    cat jest.config.delta.js
                    """,
                    ]
                )
                # Run LWC unit tests for delta components only
                .with_exec(
                    [
                        "npx",
                        "jest",
                        "--config",
                        "jest.config.delta.js",
                        "--passWithNoTests",
                        "--verbose",
                    ]
                )
                # Generate test coverage report for delta components
                .with_exec(
                    [
                        "npx",
                        "jest",
                        "--config",
                        "jest.config.delta.js",
                        "--coverage",
                        "--passWithNoTests",
                    ]
                )
                # Display test results summary
                .with_exec(["ls", "-la", "coverage-delta/"])
                # Show coverage summary if available
                .with_exec(
                    [
                        "bash",
                        "-c",
                        """
                    if [ -f "coverage-delta/lcov-report/index.html" ]; then
                        echo "Delta coverage report generated at coverage-delta/lcov-report/index.html"
                    fi
                    if [ -f "coverage-delta/coverage-summary.json" ]; then
                        echo "Delta Coverage Summary:"
                        cat coverage-delta/coverage-summary.json
                    fi
                    """,
                    ]
                )
                # Clean up temporary config
                .with_exec(["rm", "-f", "jest.config.delta.js"])
            )
        else:
            container = (
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
                )
                # Run LWC unit tests
                .with_exec(["npm", "run", "test:unit"])
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

        return container

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
        auth_url: Annotated[dagger.Secret, Doc("Salesforce auth URL for login")],
        container: dagger.Container | None = None,
        alias: Annotated[str, Doc("Alias for the org")] = "target-org",
        apex_tests: Annotated[str, Doc("Comma seperated apex test classes")] = "all",
    ) -> dagger.Container:
        """Perform a dry run deployment of delta changes to validate deployment without actually deploying."""

        if container is None:
            container = await self.prepare_delta_source(source)
            container = await self.login_sf_cli(source, auth_url, container)

        # Check if delta sources exist
        container = container.with_exec(
            [
                "bash",
                "-c",
                """
                if [ ! -d "/src/changed-sources" ]; then
                    echo "Error: Delta sources directory 'changed-sources' does not exist."
                    echo "Please run prepare-delta-source function first."
                    exit 1
                fi
                
                if [ ! -d "/src/changed-sources/force-app" ]; then
                    echo "No force-app directory found in delta sources. Nothing to deploy."
                    exit 0
                fi
                
                echo "Delta sources verified. Proceeding with dry run deployment..."
                ls -la /src/changed-sources/
                """,
            ]
        )

        # Perform dry run deployment based on apex_tests parameter
        if apex_tests.lower() == "all":
            # Run all local tests
            container = container.with_exec(
                [
                    "sf",
                    "project",
                    "deploy",
                    "start",
                    "--source-dir",
                    "changed-sources/force-app",
                    "--dry-run",
                    "--test-level",
                    "RunLocalTests",
                    "--target-org",
                    alias,
                    "--json",
                ]
            )
        else:
            # Run specified tests
            container = container.with_exec(
                [
                    "sf",
                    "project",
                    "deploy",
                    "start",
                    "--source-dir",
                    "changed-sources/force-app",
                    "--dry-run",
                    "--test-level",
                    "RunSpecifiedTests",
                    "--tests",
                    apex_tests,
                    "--target-org",
                    alias,
                    "--json",
                ]
            )

        # Display deployment results summary
        container = container.with_exec(
            [
                "bash",
                "-c",
                """
                echo "Dry run deployment completed successfully!"
                echo "No actual changes were made to the org."
                """,
            ]
        )

        return container

    @function
    async def dry_run_delta_destructive_changes(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        auth_url: Annotated[dagger.Secret, Doc("Salesforce auth URL for login")],
        container: dagger.Container | None = None,
        alias: Annotated[str, Doc("Alias for the org")] = "target-org",
    ) -> dagger.Container:
        """Perform a dry run deployment of destructive changes to validate deletion without actually deleting."""

        if container is None:
            container = await self.prepare_delta_source(source)
            container = await self.login_sf_cli(source, auth_url, container)

        # Check if destructive changes exist
        container = container.with_exec(
            [
                "bash",
                "-c",
                """
                if [ ! -d "/src/changed-sources" ]; then
                    echo "Error: Delta sources directory 'changed-sources' does not exist."
                    echo "Please run prepare-delta-source function first."
                    exit 1
                fi
                
                echo "Checking for destructive changes..."
                ls -la /src/changed-sources/
                
                if [ ! -f "/src/changed-sources/destructiveChanges/destructiveChanges.xml" ]; then
                    echo "No destructive changes found. Nothing to delete."
                    exit 0
                fi
                
                echo "Destructive changes found. Proceeding with dry run deployment..."
                cat /src/changed-sources/destructiveChanges/destructiveChanges.xml
                """,
            ]
        )

        # Deploy destructive changes with dry run
        container = container.with_exec(
            [
                "sf",
                "project",
                "deploy",
                "start",
                "--metadata-dir",
                "changed-sources/destructiveChanges",
                "--dry-run",
                "--ignore-warnings",
                "--target-org",
                alias,
                "--json",
            ]
        )

        # Display destructive deployment results summary
        container = container.with_exec(
            [
                "bash",
                "-c",
                """
                echo "Dry run destructive deployment completed successfully!"
                echo "No actual deletions were made to the org."
                echo "Review the destructive changes before running actual deployment."
                """,
            ]
        )

        return container

    @function
    async def ci_pipeline(
        self,
        source: Annotated[dagger.Directory, DefaultPath("/"), Doc("source directory")],
        auth_url: Annotated[dagger.Secret, Doc("Salesforce auth URL for login")],
        alias: Annotated[str, Doc("Alias for the org")] = "target-org",
        lwc_tests: Annotated[str, Doc("run delta or all lwc tests")] = "all",
        apex_tests: Annotated[str, Doc("Comma seperated apex test classes")] = "all",
    ) -> str:
        """
        Complete CI pipeline that builds environment, prepares delta changes,
        runs scans and tests, and performs dry-run deployments.
        """
        try:
            # Step 1: Build base container using build_env
            container = self.build_env(source)

            # Step 2: Prepare delta changes using prepare_delta_source
            container = await self.prepare_delta_source(source, container)

            # Step 3: Run scan_delta_source for code quality analysis
            container = await self.scan_delta_source(source, container)

            # Step 4: Run LWC unit tests (only if lwc_tests is not 'none')
            container = await self.run_lwc_unit_tests(source, container, lwc_tests)

            # Step 5: Login to Salesforce CLI
            container = await self.login_sf_cli(source, auth_url, container, alias)

            # Step 6: Dry run delta changes deployment
            container = await self.dry_run_delta_changes(
                source, auth_url, container, alias, apex_tests
            )

            # Step 7: Dry run destructive changes (if any)
            container = await self.dry_run_delta_destructive_changes(
                source, auth_url, container, alias
            )

            # Final validation step
            final_output = await container.with_exec(
                [
                    "bash",
                    "-c",
                    """
                echo "✅ CI Pipeline completed successfully!"
                echo "📊 Pipeline Summary:"
                echo "  - Environment built and configured"
                echo "  - Delta sources prepared and scanned"
                if [ "$1" != "none" ]; then
                    echo "  - LWC unit tests executed"
                else
                    echo "  - LWC unit tests skipped"
                fi
                echo "  - Salesforce CLI authentication successful"
                echo "  - Delta changes dry run validation passed"
                echo "  - Destructive changes dry run validation completed"
                echo ""
                echo "🎯 Ready for actual deployment!"
                echo "Use the individual functions for production deployment:"
                echo "  - deploy_delta_changes (instead of dry_run_delta_changes)"
                echo "  - deploy_destructive_changes (instead of dry_run_delta_destructive_changes)"
                """,
                    lwc_tests,
                ]
            ).stdout()

            return final_output

        except Exception as e:
            # Handle any pipeline failures gracefully
            error_container = (
                dag.container()
                .from_("ubuntu:latest")
                .with_exec(
                    [
                        "bash",
                        "-c",
                        f"""
                    echo "❌ CI Pipeline failed with error:"
                    echo "Error: {str(e)}"
                    echo ""
                    echo "🔧 Troubleshooting steps:"
                    echo "1. Check if all required files are present in the source directory"
                    echo "2. Verify the Salesforce auth URL is valid"
                    echo "3. Ensure the target org is accessible"
                    echo "4. Check if there are any syntax errors in the changed files"
                    echo "5. Review individual function logs for detailed error information"
                    echo ""
                    echo "💡 You can run individual pipeline steps to isolate the issue:"
                    echo "  - build-env: Check environment setup"
                    echo "  - prepare-delta-source: Verify delta generation"
                    echo "  - scan-delta-source: Check code quality issues"
                    echo "  - run-lwc-unit-tests: Validate LWC tests"
                    echo "  - login-sf-cli: Test Salesforce authentication"
                    exit 1
                    """,
                    ]
                )
            )

            error_output = await error_container.stdout()
            return error_output

    @function
    async def create_promotional_branch(
        self,
        base_ref: Annotated[str, Doc("Target branch name to merge into")],
        head_ref: Annotated[str, Doc("Source branch name to merge from")],
        github_token: Annotated[dagger.Secret, Doc("GitHub personal access token")],
        repo_name: Annotated[str, Doc("Repository name in format 'owner/repo'")],
    ) -> dagger.Container:
        """
        Create a promotional branch by merging source branch changes into target branch.
        Returns container with merge result or conflict information.
        """
        # Initialize logging
        promotion_branch = f"promotion/{head_ref}-to-{base_ref}"
        log_file = "promotional_branch.log"

        # Use lightweight Alpine container with only necessary dependencies
        container = (
            dag.container()
            .from_("alpine:latest")
            .with_workdir("/src")
            # Install minimal dependencies for git operations and GitHub CLI
            .with_exec(
                [
                    "apk",
                    "add",
                    "--no-cache",
                    "git",
                    "curl",
                    "bash",
                    "openssh-client",
                    "ca-certificates",
                ]
            )
            # Install GitHub CLI
            .with_exec(
                [
                    "sh",
                    "-c",
                    """
                # Download and install GitHub CLI for Alpine
                curl -fsSL https://github.com/cli/cli/releases/latest/download/gh_$(uname -s)_$(uname -m).tar.gz | tar -xz
                mv gh_*/bin/gh /usr/local/bin/
                rm -rf gh_*
                """,
                ]
            )
        )

        # Authenticate with GitHub using token
        container = (
            container.with_secret_variable("GITHUB_TOKEN", github_token).with_exec(
                ["sh", "-c", "echo $GITHUB_TOKEN | gh auth login --with-token"]
            )
            # Verify authentication
            .with_exec(["gh", "auth", "status"])
        )

        # Configure git user for merge operations
        container = container.with_exec(
            ["git", "config", "--global", "user.email", "ci@salesforce.com"]
        ).with_exec(["git", "config", "--global", "user.name", "Salesforce CI"])

        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            # Initialize log file with header
            cat > {log_file} << 'EOF'
    ========================================
    PROMOTIONAL BRANCH CREATION LOG
    ========================================
    Repository: {repo_name}
    Source Branch: {head_ref}
    Target Branch: {base_ref}
    Promotion Branch: {promotion_branch}
    Timestamp: $(date)
    ========================================

    EOF
            echo "📋 Log file initialized: {log_file}"
            """,
            ]
        )

        # Clone repository
        container = (
            container.with_exec(
                [
                    "sh",
                    "-c",
                    f"""
            echo "📥 Starting repository clone..." | tee -a {log_file}
            echo "Command: gh repo clone {repo_name} ." >> {log_file}
            """,
                ]
            )
            .with_exec(["gh", "repo", "clone", repo_name, "."])
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"""
            if [ $? -eq 0 ]; then
                echo "✅ Repository cloned successfully" | tee -a {log_file}
            else
                echo "❌ Repository clone failed" | tee -a {log_file}
                exit 1
            fi
            """,
                ]
            )
        )

        # Fetch all branches
        container = (
            container.with_exec(
                [
                    "sh",
                    "-c",
                    f"""
            echo "🔄 Fetching all branches..." | tee -a {log_file}
            echo "Command: git fetch --all" >> {log_file}
            """,
                ]
            )
            .with_exec(["git", "fetch", "--all"])
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"""
            if [ $? -eq 0 ]; then
                echo "✅ All branches fetched successfully" | tee -a {log_file}
                echo "Available branches:" >> {log_file}
                git branch -r >> {log_file}
            else
                echo "❌ Failed to fetch branches" | tee -a {log_file}
                exit 1
            fi
            """,
                ]
            )
        )

        # Verify source branch exists
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            echo "🔍 Verifying source branch '{head_ref}'..." | tee -a {log_file}
            if git show-ref --verify --quiet refs/remotes/origin/{head_ref}; then
                echo "✅ Source branch '{head_ref}' exists" | tee -a {log_file}
            else
                echo "❌ Error: Source branch '{head_ref}' does not exist" | tee -a {log_file}
                echo "Available remote branches:" >> {log_file}
                git branch -r >> {log_file}
                exit 1
            fi
            """,
            ]
        )

        # Verify target branch exists
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            echo "🔍 Verifying target branch '{base_ref}'..." | tee -a {log_file}
            if git show-ref --verify --quiet refs/remotes/origin/{base_ref}; then
                echo "✅ Target branch '{base_ref}' exists" | tee -a {log_file}
            else
                echo "❌ Error: Target branch '{base_ref}' does not exist" | tee -a {log_file}
                echo "Available remote branches:" >> {log_file}
                git branch -r >> {log_file}
                exit 1
            fi
            """,
            ]
        )

        # Create promotional branch
        container = (
            container.with_exec(
                [
                    "sh",
                    "-c",
                    f"""
            echo "🌿 Creating promotional branch '{promotion_branch}' from target branch..." | tee -a {log_file}
            echo "Command: git checkout -b {promotion_branch} origin/{base_ref}" >> {log_file}
            """,
                ]
            )
            .with_exec(
                ["git", "checkout", "-b", promotion_branch, f"origin/{base_ref}"]
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"""
            if [ $? -eq 0 ]; then
                echo "✅ Promotional branch created successfully" | tee -a {log_file}
                echo "Current branch: $(git branch --show-current)" >> {log_file}
            else
                echo "❌ Failed to create promotional branch" | tee -a {log_file}
                exit 1
            fi
            """,
                ]
            )
        )

        # Attempt merge
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
                echo "🔀 Attempting to merge '{head_ref}' into '{promotion_branch}'..." | tee -a {log_file}
                echo "Command: git merge origin/{head_ref} --no-edit --no-ff" >> {log_file}
                echo "Merge attempt started at: $(date)" >> {log_file}
                """,
            ]
        )

        # Perform the actual merge and handle results
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
                # Attempt the merge
                if git merge origin/{head_ref} --no-edit --no-ff; then
                    echo "✅ Merge completed successfully without conflicts" | tee -a {log_file}
                    echo "Merge completed at: $(date)" >> {log_file}
                    
                    # Log merge statistics
                    echo "" >> {log_file}
                    echo "=== MERGE STATISTICS ===" >> {log_file}
                    git log --oneline {base_ref}..{promotion_branch} >> {log_file}
                    echo "" >> {log_file}
                    
                    # Set success flag
                    echo "MERGE_SUCCESS=true" > merge_result.env
                else
                    echo "⚠️ Merge conflicts detected!" | tee -a {log_file}
                    echo "Merge conflict detected at: $(date)" >> {log_file}
                    
                    # Get list of conflicted files
                    conflicted_files=$(git diff --name-only --diff-filter=U)
                    echo "📋 Conflicted files:" | tee -a {log_file}
                    echo "$conflicted_files" | tee -a {log_file}
                    
                    # Set failure flag
                    echo "MERGE_SUCCESS=false" > merge_result.env
                    echo "CONFLICTED_FILES<<EOF" >> merge_result.env
                    echo "$conflicted_files" >> merge_result.env
                    echo "EOF" >> merge_result.env
                fi
                """,
            ]
        )

        # Handle successful merge
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then
                echo "📤 Pushing promotional branch to remote..." | tee -a {log_file}
                echo "Command: git push origin {promotion_branch}" >> {log_file}
            fi
            """,
            ]
        ).with_exec(
            [
                "sh",
                "-c",
                f"""
            if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then
                git push origin {promotion_branch}
                if [ $? -eq 0 ]; then
                    echo "✅ Promotional branch pushed successfully" | tee -a {log_file}
                    echo "🎉 Promotional branch '{promotion_branch}' created successfully!" | tee -a {log_file}
                    echo "🔗 Branch URL: https://github.com/{repo_name}/tree/{promotion_branch}" | tee -a {log_file}
                    echo "Push completed at: $(date)" >> {log_file}
                else
                    echo "❌ Failed to push promotional branch" | tee -a {log_file}
                    exit 1
                fi
            fi
            """,
            ]
        )

        # Handle merge conflicts
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=false" merge_result.env; then
                echo "" >> {log_file}
                echo "=== CONFLICT ANALYSIS ===" >> {log_file}
                
                # Get conflicted files from environment
                conflicted_files=$(git diff --name-only --diff-filter=U)
                
                for file in $conflicted_files; do
                    echo "=== Analyzing conflicts in $file ===" >> {log_file}
                    
                    # Show conflict markers and context
                    echo "--- Conflicted content ---" >> {log_file}
                    cat "$file" >> {log_file} 2>/dev/null || echo "Unable to read file" >> {log_file}
                    echo "" >> {log_file}
                    
                    # Try to show individual versions
                    echo "--- Target branch version ({base_ref}) ---" >> {log_file}
                    git show ":2:$file" >> {log_file} 2>/dev/null || echo "File not found in target" >> {log_file}
                    echo "" >> {log_file}
                    
                    echo "--- Source branch version ({head_ref}) ---" >> {log_file}
                    git show ":3:$file" >> {log_file} 2>/dev/null || echo "File not found in source" >> {log_file}
                    echo "" >> {log_file}
                    echo "========================================" >> {log_file}
                done
                
                # Abort the merge to clean state
                echo "🔄 Aborting merge to restore clean state..." | tee -a {log_file}
                git merge --abort
                
                echo "" >> {log_file}
                echo "❌ Promotional branch creation failed due to conflicts" | tee -a {log_file}
                echo "🔧 Manual resolution required for files listed above" | tee -a {log_file}
                echo "Conflict analysis completed at: $(date)" >> {log_file}
            fi
            """,
            ]
        )

        # Generate final summary
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            echo "" >> {log_file}
            echo "=== FINAL SUMMARY ===" >> {log_file}
            echo "Operation completed at: $(date)" >> {log_file}
            
            if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then
                echo "Result: SUCCESS" >> {log_file}
                echo "Promotional branch '{promotion_branch}' is ready for use" >> {log_file}
            else
                echo "Result: FAILED - CONFLICTS DETECTED" >> {log_file}
                echo "Manual intervention required" >> {log_file}
            fi
            
            echo "========================================" >> {log_file}
            
            # Display final status
            echo "📋 Operation Summary:"
            if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then
                echo "✅ Promotional branch creation completed successfully"
                echo "📁 Branch: {promotion_branch}"
                echo "🔗 URL: https://github.com/{repo_name}/tree/{promotion_branch}"
            else
                echo "❌ Promotional branch creation failed due to merge conflicts"
                echo "📝 Check the log file for detailed conflict information"
            fi
            
            echo ""
            echo "📄 Full log available in: {log_file}"
            echo "📊 Log summary:"
            wc -l {log_file}
            """,
            ]
        )

        # Display log file for debugging
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            echo "=== LOG FILE CONTENTS ==="
            cat {log_file}
            echo "=== END LOG FILE ==="
            """,
            ]
        )

        # Export log files and results
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"""
            # Create logs directory for export
            mkdir -p /src/logs
            
            # Copy main log file with timestamp
            timestamp=$(date +%Y%m%d_%H%M%S)
            cp {log_file} /src/logs/promotional_branch_${{timestamp}}.log
            
            # Copy merge result environment file if it exists
            if [ -f merge_result.env ]; then
                cp merge_result.env /src/logs/
            fi
            
            # Create comprehensive summary file
            cat > /src/logs/summary.txt << EOF
            Promotional Branch Operation Summary
            ===================================
            Repository: {repo_name}
            Source Branch: {head_ref}
            Target Branch: {base_ref}
            Promotion Branch: {promotion_branch}
            Operation Time: $(date)

            Status: $(if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then echo "SUCCESS"; else echo "FAILED"; fi)

            Files Generated:
            - promotional_branch_${{timestamp}}.log (detailed operation log)
            - merge_result.env (operation status and results)
            - summary.txt (this summary file)

            $(if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then
            echo "SUCCESS: Promotional branch created successfully!
            Branch URL: https://github.com/{repo_name}/tree/{promotion_branch}
            Next steps:
            1. Review the promotional branch
            2. Create a pull request if needed
            3. Deploy to target environment"
            else
            echo "FAILURE: Merge conflicts detected!
            Next steps:
            1. Review the detailed log for conflict analysis
            2. Manually resolve conflicts in a local environment
            3. Re-attempt the promotional branch creation"
            fi)

            Log Summary:
            - Total log lines: $(wc -l < /src/logs/promotional_branch_${{timestamp}}.log)
            - Operation duration: Started at $(head -n 10 /src/logs/promotional_branch_${{timestamp}}.log | grep "Timestamp:" | cut -d: -f2-)

            EOF
                    
                    # Create a JSON summary for programmatic access
                    cat > /src/logs/operation_result.json << EOF
            {{
            "repository": "{repo_name}",
            "source_branch": "{head_ref}",
            "target_branch": "{base_ref}",
            "promotion_branch": "{promotion_branch}",
            "timestamp": "$(date -Iseconds)",
            "success": $(if [ -f merge_result.env ] && grep -q "MERGE_SUCCESS=true" merge_result.env; then echo "true"; else echo "false"; fi),
            "log_file": "promotional_branch_${{timestamp}}.log",
            "branch_url": "https://github.com/{repo_name}/tree/{promotion_branch}"
            }}
            EOF
            
            echo "📄 Log files exported to /src/logs/"
            echo "📊 Export summary:"
            ls -la /src/logs/
            """,
            ]
        )

        return container.export("/src/logs")
