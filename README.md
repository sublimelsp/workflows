# LSP Workflows

## Changed Settings

Compare VSCode-specific settings between two tags and report results in the PR.

Example workflow:

```yaml
name: Check settings

on:
  pull_request:
    branches:
    - main

jobs:
  check-new-settings:
    uses: sublimelsp/workflows/.github/workflows/new-json-settings.yaml
    with:
      repository_url: 'https://github.com/rust-lang/rust-analyzer'
      configuration_file_path: 'editors/code/package.json'
      configuration_jq_query: '.contributes.configuration.properties'
      version_file: 'plugin.py'
      version_regexp: 'TAG = "([^"]+)"'
```
