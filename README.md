# LSP Workflows

Reusable GitHub Actions workflows and a CLI for tracking JSON schema-based settings of an upstream language server across releases.

Both workflows read a `settings-processor.json` config file (see [Configuration](#configuration)) from the calling repository's working directory. It declares the upstream repository, the path to its configuration file, and how to transform/render it.

## Workflows

### Changed Settings

`changed-settings.yaml` runs on a pull request. It extracts the upstream version from a file on the default branch and on the PR branch, and - if the version changed - regenerates the settings, commits the result to the PR, and posts a diff as a PR comment.

```yaml
name: Check settings

on:
  pull_request:
    branches:
    - main

jobs:
  check-settings:
    uses: sublimelsp/workflows/.github/workflows/changed-settings.yaml@v2
    with:
      # Repo-relative path to the file that contains the upstream version.
      version_file: 'plugin.py'
      # Regexp to extract the version; the first capturing group is the tag.
      version_regexp: 'TAG = "([^"]+)"'
      # Optional. Transforms the captured tag; `{}` is replaced with the tag (e.g. to prepend a 'v').
      version_transform: 'v{}'
```

Inputs:

| Input | Required | Default | Description |
|---|---|---|---|
| `version_file` | yes | - | Repo-relative path to the file that contains version information. |
| `version_regexp` | yes | - | Regexp pattern to extract the version. The first capturing group must match the release tag in the upstream repository. |
| `version_transform` | no | `{}` | String used to transform the captured tag. `{}` is replaced with the captured tag. |

Outputs: `version_changed`, `new_version`, `settings_changed`.

### Update Settings

`update-settings.yaml` takes no inputs. It looks up the latest release of the upstream repository (via `gh release view`) using `input_repository_url` from `settings-processor.json`, regenerates the settings for that tag, commits any changes to the PR branch, and posts a comment.

```yaml
name: Update settings

on:
  workflow_dispatch:

jobs:
  update:
    uses: sublimelsp/workflows/.github/workflows/update-settings.yaml@v2
```

## Configuration

Both workflows and the CLI require a `settings-processor.json` file in the working directory:

```json
{
  "input_repository_url": "https://github.com/rust-lang/rust-analyzer",
  "input_repository_json_configuration_path": "editors/code/package.json",
  "transformers": [
    {
      "type": "jq",
      "options": ".contributes.configuration.properties"
    }
  ],
  "render_templates": [
    {
      "type": "settings",
      "template_path": "templates/settings.tmpl",
      "output_path": "LSP-rust-analyzer.sublime-settings"
    }
  ]
}
```

| Key | Description |
|---|---|
| `input_repository_url` | GitHub URL of the upstream repository containing the configuration file. |
| `input_repository_json_configuration_path` | Path to the configuration file, relative to the upstream repository root. |
| `transformers` | Ordered list of transforms applied to the parsed configuration. |
| `render_templates` | Templates to render from the resulting settings. |

Transformer types:

| `type` | `options` | Effect |
|---|---|---|
| `jq` | jq query string | Runs the query against the configuration JSON. |
| `prepend_keys` | object | Merges the given keys in front of the configuration. |
| `remove_keys` | list of strings | Removes the given top-level keys. |

Each `render_templates` entry has a `type` (`settings` or `schema`), a `template_path`, and an `output_path`. The Jinja2 template receives the rendered settings as the `settings` variable.

## Running locally

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/)

Install dependencies:

```sh
uv sync
```

Run with a `settings-processor.json` in the working directory. Pass one tag to generate settings for that tag, or two tags to also produce a diff between them:

```sh
uv run scripts/changed_settings.py <tag_from> <tag_to>
```

Using the rust-analyzer example above, comparing tags `2024-11-25` and `2024-12-02`:

```sh
uv run scripts/changed_settings.py 2024-11-25 2024-12-02
```

### Installing globally

To make `changed-settings` available as a command anywhere on your system, install the package in editable (dev) mode:

```sh
uv tool install --editable .
```

The command can then be invoked directly without `uv run` or a script path:

```sh
changed-settings 2024-11-25 2024-12-02
```

To uninstall: `uv tool uninstall workflows`

### Options

| Flag | Default | Description |
|---|---|---|
| `--config` | `settings-processor.json` | Path to the configuration file (see [Configuration](#configuration)). |
