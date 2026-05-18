# LSP Workflows

## Changed Settings

Compare JSON schema-based settings between two tags and report results in the PR.

Example workflow:

```yaml
name: Check settings

on:
  pull_request:
    branches:
    - main

jobs:
  check-settings:
    uses: sublimelsp/workflows/.github/workflows/changed-settings.yaml@main
    with:
      repository_url: 'https://github.com/rust-lang/rust-analyzer'
      configuration_file_path: 'editors/code/package.json'
      # Optional
      configuration_jq_query: '.contributes.configuration.properties'
      # Optional
      schema_overrides_path: 'sublime-package.overrides.json'
      version_file: 'plugin.py'
      version_regexp: 'TAG = "([^"]+)"'
      # Optional string used to transform the tag captured by version_regexp. This can for example add a 'v' in front of the tag. The {} is replaced with the captured tag.
      version_transform: '{}'
```

### Running locally

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/)

Install dependencies:

```sh
uv sync
```

A `settings-processor.json` config file is required in the working directory. See `--config` in the optional flags below.

```sh
uv run scripts/changed_settings.py \
  <repository_url> \
  <configuration_file_path> \
  <tag_from> \
  <tag_to>
```

Using the rust-analyzer example above, comparing tags `2024-11-25` and `2024-12-02`:

```sh
uv run scripts/changed_settings.py \
  https://github.com/rust-lang/rust-analyzer \
  editors/code/package.json \
  2024-11-25 \
  2024-12-02
```

#### Installing globally

To make `changed-settings` available as a command anywhere on your system, install the package in editable (dev) mode:

```sh
uv tool install --editable .
```

The command can then be invoked directly without `uv run` or a script path:

```sh
changed-settings \
  https://github.com/rust-lang/rust-analyzer \
  editors/code/package.json \
  2024-11-25 \
  2024-12-02
```

To uninstall: `uv tool uninstall workflows`

Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--config` | `settings-processor.json` | Path to a JSON file with `add`, `remove`, and/or `transform` keys to augment the schema. |
