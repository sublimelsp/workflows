#!/usr/bin/env python3

"""Prints differences in server settings between two tags."""

from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.request import urlopen
import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


class Configuration(TypedDict):
    type: str
    default: bool | int | str | None
    description: str
    markdownDescription: str


type ConfigurationsDict = dict[str, Configuration]


def download_github_artifact_by_tag(repository_url: str, tag: str, target_dir: str) -> Path:
    archive_url = f'{repository_url}/archive/{tag}.zip'
    zip_path = Path(target_dir, f'archive-{re.sub(r'[<>:"/\\|?*]', '_', tag)}.zip')

    with urlopen(archive_url) as response, Path.open(zip_path, 'wb') as out_file:  # noqa: S310
        shutil.copyfileobj(response, out_file)

    return zip_path


def extract_configuration_file(zip_path: Path, configuration_path: str, target_dir: str) -> Path:
    with zipfile.ZipFile(zip_path, 'r') as zip_file:
        filepath = next((p for p in zip_file.namelist() if configuration_path in p), None)
        if not filepath:
            print(f'Archive does not contain expected file {configuration_path}')
            sys.exit(1)
        return Path(zip_file.extract(filepath, target_dir))


def generate_sublime_settings_markdown(settings: dict[str, Configuration]) -> str:
    sublime_settings: list[str] = []
    for key, value in settings.items():
        description: str = value['markdownDescription'] if 'markdownDescription' in value else value['description']
        wrapped_description: str = '\n'.join([f'// {line}'.rstrip() for line in description.splitlines()])
        sublime_settings.append(f'{wrapped_description}\n"{key}": {json_serialize(value['default'])},')
    sublime_settings_str = '\n\n'.join(sublime_settings)
    return f'```\n{sublime_settings_str}\n```'


def compare_json(
    jq_query: str, contents_1: str, contents_2: str
) -> tuple[dict[str, Configuration], dict[str, Configuration], list[str]]:
    flatten_settings_1 = jq(jq_query, contents_1)
    flatten_settings_2 = jq(jq_query, contents_2)

    # Find added, removed and changed keys.
    added: dict[str, Configuration] = {}
    changed: dict[str, Configuration] = {}
    removed: list[str] = [key for key in flatten_settings_1 if key not in flatten_settings_2]
    for key, value in flatten_settings_2.items():
        if key not in flatten_settings_1:
            added[key] = value
            continue

        if value != flatten_settings_1[key]:
            changed[key] = value

    return (added, changed, removed)


def jq(query: str, contents: str) -> ConfigurationsDict:
    return cast(ConfigurationsDict,
                json.loads(subprocess.check_output(['jq', query], input=contents, text=True, encoding='utf-8')))


def json_serialize(contents: Any) -> str:
    return json.dumps(contents, indent=2)


def markdown_collapsible_section(summary: str, contents: str) -> str:
    return f"""<details>

<summary>{summary}</summary>

{contents}

</details>"""


def main() -> None:
    parser = argparse.ArgumentParser(description='Checks for differences in configuration between two tags')
    parser.add_argument('repository_url',
                        help='The github URL to the repository that contains the configuration to check file..')
    parser.add_argument('configuration_file_path',
                        help='A path to the configuration file relative to the repository_url.')
    parser.add_argument('configuration_jq_query',
                        help='The JQ query to use to retrieve configuration settings.')
    parser.add_argument('tag_from', help='First tag to compare.')
    parser.add_argument('tag_to', help='Second tag to compare.')
    args = parser.parse_args()

    repository_url: str = args.repository_url
    configuration_file_path: str = args.configuration_file_path
    configuration_jq_query: str = args.configuration_jq_query
    tag_from: str = args.tag_from
    tag_to: str = args.tag_to

    with tempfile.TemporaryDirectory() as tempdir:
        archive_path_1 = download_github_artifact_by_tag(repository_url, tag_from, tempdir)
        configuration_path_1 = extract_configuration_file(archive_path_1, configuration_file_path, tempdir)
        archive_path_2 = download_github_artifact_by_tag(repository_url, tag_to, tempdir)
        configuration_path_2 = extract_configuration_file(archive_path_2, configuration_file_path, tempdir)

        with Path.open(configuration_path_1, encoding='utf-8') as f1, \
                Path.open(configuration_path_2, encoding='utf-8') as f2:
            configuration_1 = f1.read()
            configuration_2 = f2.read()

        diff = '\n'.join(difflib.unified_diff(
            configuration_1.split('\n'),
            configuration_2.split('\n'),
            fromfile=tag_from,
            tofile=tag_to,
            lineterm=''))

        output: list[str] = [
            f'Following are the [settings schema]({repository_url}/blob/{tag_to}{configuration_file_path}) changes between tags `{tag_from}` and `{tag_to}`. Make sure that those are reflected in the package settings and the `sublime-package.json` file.\n'
        ]

        if diff:
            added, changed, removed = compare_json(configuration_jq_query, configuration_1, configuration_2)

            if added:
                output.append(markdown_collapsible_section(f'Added keys ({len(added.keys())})',
                                                           f'```json\n{json_serialize(added)}\n```'))
                output.append(markdown_collapsible_section('New sublime settings',
                                                           generate_sublime_settings_markdown(added)))

            if changed:
                output.append(markdown_collapsible_section(f'Changed keys ({len(changed.keys())})',
                                                           f'```json\n{json_serialize(changed)}\n```'))
                output.append(markdown_collapsible_section('Changed sublime settings',
                                                           generate_sublime_settings_markdown(changed)))

            if removed:
                key_list = '\n'.join([f' - `{k}`' for k in removed])
                output.append(f'Removed keys (${len(key_list)}):\n{key_list}')

            output.append(markdown_collapsible_section(f'All changes in `{configuration_file_path}`',
                                                       f'```diff\n{diff}\n```'))
        else:
            output.append('No changes')

        print('\n\n'.join(output))

main()
