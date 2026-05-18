#!/usr/bin/env python3

"""Prints differences in server settings between two tags."""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from typing import cast
from typing import Literal
from typing import NotRequired
from typing import TypedDict
from urllib.error import HTTPError
from urllib.request import urlopen
import argparse
import difflib
import jinja2
import json
import re
import shutil
import subprocess
import tempfile
import zipfile


class Setting(TypedDict):
    type: str | list[str]
    default: NotRequired[bool | int | str | None]
    description: NotRequired[str]
    markdownDescription: NotRequired[str]
    enum: NotRequired[list[str]]
    enumDescriptions: NotRequired[list[str]]
    markdownEnumDescriptions: NotRequired[list[str]]


type SettingsDict = dict[str, Setting]


class LocalizationObject(TypedDict):
    message: str
    comment: NotRequired[str]


class Config(TypedDict):
    input_repository_url: str
    """The github URL to the repository that contains the configuration to check file."""
    input_repository_json_configuration_path: str
    """A path to the configuration file relative to the repository_url."""
    transformers: list[Transformer]
    render_templates: list[TemplateOptions]


class TemplateOptions(TypedDict):
    type: Literal['settings', 'schema']
    template_path: str
    output_path: str


class TransformerJson(TypedDict):
    type: Literal['jq']
    options: str


class TransformerPrependKeys(TypedDict):
    type: Literal['prepend_keys']
    options: Any


class TransformerRemoveKeys(TypedDict):
    type: Literal['remove_keys']
    options: list[str]


Transformer = TransformerJson | TransformerPrependKeys | TransformerRemoveKeys


class Output:
    def __init__(self) -> None:
        self._info: list[str] = []
        self._warnings: list[str] = []

    def info(self, message: str) -> None:
        self._info.append(message)

    def warning(self, message: str) -> None:
        self._warnings.append(message)

    def flush(self) -> None:
        print('\n'.join(self._info))
        self._info = []
        if self._warnings:
            print(markdown_collapsible_section(f'warnings ({len(self._warnings)})',
                                               '\n'.join([f' - {w}' for w in self._warnings])))
            self._warnings = []


output = Output()


def download_github_artifact_by_tag(repository_url: str, tag: str, target_dir: str) -> Path:
    archive_url = f'{repository_url}/archive/refs/tags/{tag}.zip'
    zip_path = Path(target_dir, f'archive-{re.sub(r'[<>:"/\\|?*]', '_', tag)}.zip')
    try:
        with urlopen(archive_url) as response, zip_path.open('wb') as out_file:
            shutil.copyfileobj(response, out_file)
    except HTTPError as e:
        raise RuntimeError(f'HTTP {e.code}, fetching {archive_url!r}: {e.reason}') from e
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
            translations_json: dict[str, str | LocalizationObject] = json.loads(translations)
            for key, value in translations_json.items():
                configuration = configuration.replace(
                    f'"%{key}%"', json_serialize(value if isinstance(value, str) else value['message']))
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


def process_transformers(data: SettingsDict, transformers: list[Transformer] | None = None) -> SettingsDict:
    for transformer in transformers or []:
        if transformer['type'] == 'jq':
            options = transformer['options']
            data = jq(options, json.dumps(data))
        elif transformer['type'] == 'prepend_keys':
            options = transformer['options']
            data = {**options, **data}
        elif transformer['type'] == 'remove_keys':
            for key in transformer['options']:
                if key in data:
                    data.pop(key)
    return data


def generate_sublime_settings(settings: SettingsDict) -> str:
    sublime_settings: list[str] = []
    for key, value in settings.items():
        if 'default' not in value:
            output.warning(f'skipping key `{key}` in generated settings because it has no default value')
            continue
        if description := get_description(value):
            wrapped_description: str = '\n'.join([f'// {line}'.rstrip() for line in description.splitlines()])
            sublime_settings.append(
                f'{wrapped_description}\n"{key}": {json_serialize(value['default'], indent='\t')},')
        else:
            sublime_settings.append(
                f'"{key}": {json_serialize(value['default'], indent='\t')},')
    return '\n'.join(sublime_settings)


def get_description(value: Setting) -> str | None:
    if 'markdownDescription' in value:
        return value['markdownDescription']
    if 'description' in value:
        return value['description']
    if 'enum' in value:
        if descriptions := value.get('enumDescriptions', value.get('markdownEnumDescriptions', [])):
            return '\n'.join([f'{value['enum'][i]} - {descriptions[i]}' for i, _ in enumerate(value['enum'])])
    return None


# def get_default_value(key: str, value: Setting) -> Any:
#     if 'default' in value:
#         return value['default']
#     print(f'warning: adding null default value for {key} due to no default value specified')
#     if value['type'] == 'object':
#         return {}
#     if isinstance(value['type'], list):
#         if 'null' in value['type']:
#             return None
#         value['type'].append('null')
#     else:
#         value['type'] = [value['type'], 'null']
#     return None


def compare_settings(
    settings_1: SettingsDict, settings_2: SettingsDict
) -> tuple[SettingsDict, SettingsDict, list[str]]:
    # Find added, removed and changed keys.
    added: SettingsDict = {}
    changed: SettingsDict = {}
    removed: list[str] = [key for key in settings_1 if key not in settings_2]
    for key, value in settings_2.items():
        if key not in settings_1:
            added[key] = value
            continue
        if value != settings_1[key]:
            changed[key] = value
    return (added, changed, removed)


def jq(query: str, contents: str) -> SettingsDict:
    try:
        return cast('SettingsDict',
                    json.loads(subprocess.check_output(['jq', query], input=contents, text=True, encoding='utf-8')))  # noqa: S607
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f'Error running jq command: {e.cmd} for input:\n{contents}') from e


def json_serialize(contents: Any, indent: int | str = 2) -> str:
    return json.dumps(contents, indent=indent)


def markdown_collapsible_section(summary: str, contents: str) -> str:
    return f"""\n<details>

<summary>{summary}</summary>

{contents}

</details>\n"""


def main() -> None:

    class CmdLineArgs(argparse.Namespace):
        tag_from: str  # repurposed as tag_to when tag_to is omitted
        tag_to: str | None
        config: str
        output_schema_path: str | None
        output_settings_path: str | None

    parser = argparse.ArgumentParser(description='Checks for differences in configuration between two tags')
    parser.add_argument('tag_from', help='From tag, or to tag if tag_to is not specified.')
    parser.add_argument('tag_to', nargs='?', default=None, help='To tag.')
    parser.add_argument('--config',
                        default='settings-processor.json',
                        help='A path to file with augmentation used to transform the full schema.')
    args = parser.parse_args(namespace=CmdLineArgs())

    config_path = Path(args.config)
    tag_from = args.tag_from if args.tag_to is not None else None
    tag_to = args.tag_to if args.tag_to is not None else args.tag_from

    config: Config = json.loads(config_path.read_text(encoding='utf-8'))
    repository_url = config['input_repository_url']
    configuration_file_path = config['input_repository_json_configuration_path']

    with tempfile.TemporaryDirectory() as tempdir:
        archive_path_2 = download_github_artifact_by_tag(repository_url, tag_to, tempdir)
        configuration_2 = read_configuration_file(archive_path_2, configuration_file_path, tempdir)

        if tag_from is not None:
            archive_path_1 = download_github_artifact_by_tag(repository_url, tag_from, tempdir)
            configuration_1 = read_configuration_file(archive_path_1, configuration_file_path, tempdir)

            diff = '\n'.join(difflib.unified_diff(
                configuration_1.split('\n'),
                configuration_2.split('\n'),
                fromfile=tag_from,
                tofile=tag_to,
                lineterm=''))
        else:
            configuration_1 = None
            diff = None

        schema_url_from = f'{repository_url}/blob/{tag_from}/{configuration_file_path}'
        schema_url_to = f'{repository_url}/blob/{tag_to}/{configuration_file_path}'
        output.info('### Check & update settings')
        output.info(
            f'Checking tag range [{tag_from}]({schema_url_from})..[{tag_to}]({schema_url_to})'
            if tag_from is not None else
            f'Checking tag [{tag_to}]({schema_url_to})'
        )

        transformers = config.get('transformers')
        settings_2 = process_transformers(json.loads(configuration_2), transformers)

        if diff:
            settings_1 = process_transformers(json.loads(configuration_1), transformers)  # type: ignore[arg-type]
            added, changed, removed = compare_settings(settings_1, settings_2)

            if added:
                output.info(markdown_collapsible_section(
                    f'Added keys ({len(added.keys())})',
                    f'```json\n{json_serialize(added)}\n```\n```jsonc\n{generate_sublime_settings(added)}\n```'))

            if changed:
                output.info(markdown_collapsible_section(
                    f'Changed keys ({len(changed.keys())})',
                    f'```json\n{json_serialize(changed)}\n```\n```jsonc\n{generate_sublime_settings(changed)}\n```'))

            if removed:
                key_list = '\n'.join([f' - `{k}`' for k in removed])
                output.info(f'Removed keys (${len(key_list)}):\n{key_list}')

            output.info(markdown_collapsible_section('All changes in the configuration file', f'```diff\n{diff}\n```'))
        elif diff is not None:
            output.info('No changes')

        if templates := config.get('render_templates', []):
            jinja_env = jinja2.Environment(autoescape=False, keep_trailing_newline=True)  # noqa: S701
            for template in templates:
                tpl = jinja_env.from_string(Path(template['template_path']).read_text(encoding='utf-8'))
                if template['type'] == 'settings':
                    settings = generate_sublime_settings(settings_2)
                elif template['type'] == 'schema':
                    settings = json_serialize(settings_2)
                else:
                    raise RuntimeError(f'Unknown template type "{template['type']}"')
                Path(template['output_path']).write_text(tpl.render(settings=settings), encoding='utf-8')

        output.flush()


if __name__ == '__main__':
    main()
