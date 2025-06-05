const { jestConfig } = require("@salesforce/sfdx-lwc-jest/config");

module.exports = {
  ...jestConfig,
  modulePathIgnorePatterns: ["<rootDir>/.localdevserver"],
  coverageDirectory: "coverage",
  collectCoverage: true,
  collectCoverageFrom: [
    "force-app/main/default/lwc/**/*.js",
    "!**/node_modules/**",
    "!**/__tests__/**",
    "!**/staticresources/**"
  ]
};
