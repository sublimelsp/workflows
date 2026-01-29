#!/usr/bin/env python3

"""Prints differences in server settings between two tags."""

from pathlib import Path, PurePosixPath
from typing import Any, TypedDict, cast
from urllib.error import HTTPError
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
    try:
        with urlopen(archive_url) as response, zip_path.open('wb') as out_file:  # noqa: S310
            shutil.copyfileobj(response, out_file)
    except HTTPError as ex:
        print(f'Error downloading {archive_url}')
        raise ex
    return zip_path


def read_configuration_file(zip_path: Path, configuration_path: str, target_dir: str) -> str:
    with zipfile.ZipFile(zip_path, 'r') as zip_file:
        configuration = read_file_from_zip(zip_file, configuration_path, target_dir)
        if configuration is None:
            raise Exception(f'Archive does not contain expected file {configuration_path}')
        # Optionally get translation file and update string references.
        translations_path = str(PurePosixPath(configuration_path).with_suffix('.nls.json'))
        translations = read_file_from_zip(zip_file, translations_path, target_dir)
        if translations:
            translations_json: dict[str, str] = json.loads(translations)
            for key, value in translations_json.items():
                configuration = configuration.replace(f'"%{key}%"', json_serialize(value))
        return configuration


def read_file_from_zip(zip_file: zipfile.ZipFile, path: str, target_dir: str) -> str | None:
    parent_name = get_parent_directory(zip_file)
    archive_path = f'{parent_name}/{path}' if parent_name else path
    filepath = next((p for p in zip_file.namelist() if archive_path == p), None)
    if not filepath:
        return None
    extracted_path = Path(zip_file.extract(filepath, target_dir))
    return extracted_path.read_text(encoding='utf-8')


def get_parent_directory(zip_file: zipfile.ZipFile) -> str | None:
    """
    Check if all files in the ZIP are contained within a parent directory.
    Returns str | None: Common parent name if present.
    """

    # Filter out directory entries and get top-level paths.
    top_levels: set[str] = set()
    for name in zip_file.namelist():
        # Skip empty entries
        if not name:
            continue
        # Get the first component of the path
        top_level = name.split('/')[0]
        top_levels.add(top_level)
        # If there's only one top-level entry, all files share a parent
    return top_levels.pop() if len(top_levels) == 1 else None


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
        configuration_1 = read_configuration_file(archive_path_1, configuration_file_path, tempdir)
        archive_path_2 = download_github_artifact_by_tag(repository_url, tag_to, tempdir)
        configuration_2 = read_configuration_file(archive_path_2, configuration_file_path, tempdir)

        diff = '\n'.join(difflib.unified_diff(
            configuration_1.split('\n'),
            configuration_2.split('\n'),
            fromfile=tag_from,
            tofile=tag_to,
            lineterm=''))

        schema_url = f'{repository_url}/blob/{tag_to}{configuration_file_path}'
        output: list[str] = [
            f'Following are the [settings schema]({schema_url}) changes between tags `{tag_from}` and `{tag_to}`. '
            'Make sure that those are reflected in the package settings and `sublime-package.json`.\n'
        ]

        if diff:
            added, changed, removed = compare_json(configuration_jq_query, configuration_1, configuration_2)

            if added:
                output.append(markdown_collapsible_section(
                    f'Added keys ({len(added.keys())})',
                    f'```json\n{json_serialize(added)}\n```\n{generate_sublime_settings_markdown(added)}'))

            if changed:
                output.append(markdown_collapsible_section(
                    f'Changed keys ({len(changed.keys())})',
                    f'```json\n{json_serialize(changed)}\n```\n{generate_sublime_settings_markdown(changed)}'))

            if removed:
                key_list = '\n'.join([f' - `{k}`' for k in removed])
                output.append(f'Removed keys (${len(key_list)}):\n{key_list}')

            output.append(markdown_collapsible_section('All changes in schema', f'```diff\n{diff}\n```'))
        else:
            output.append('No changes')

        print('\n\n'.join(output))

main()
