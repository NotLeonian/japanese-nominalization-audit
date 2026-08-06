import html
import json
import os
import re
import subprocess
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST_PATH = ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = ROOT / ".agents" / "plugins" / "marketplace.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = ROOT / "tests" / "pyproject.toml"
TEST_COMMAND = "python -B -m unittest discover -s tests -p 'test_*.py' -v"
PYTHON_CHECK_COMMANDS = (
    "ruff format --check --config tests/pyproject.toml tests/test_repository.py",
    "ruff check --config tests/pyproject.toml tests/test_repository.py",
    "mypy --config-file tests/pyproject.toml tests/test_repository.py",
    "pyright --project tests/pyproject.toml tests/test_repository.py",
)
SUPPORTED_CI_RUNNERS = ("windows-latest", "macos-latest", "ubuntu-latest")

NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9]\d*)\."
    r"(?:0|[1-9]\d*)\."
    r"(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
MARKDOWN_ESCAPED_PUNCTUATION_PATTERN = re.compile(
    r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])"
)
SKILL_VERSION_PATTERN = re.compile(r'^metadata:\n  version: "([^"]+)"$', re.MULTILINE)
JAPANESE_CHARACTER_PATTERN = re.compile(r"[ぁ-んァ-ヶ一-龠々]")
HIRAGANA_PATTERN = re.compile(r"[ぁ-ん]")
YAML_NON_STRING_SCALARS = {
    "~",
    "false",
    "n",
    "no",
    "null",
    "off",
    "on",
    "true",
    "y",
    "yes",
}


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )


def iter_string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_string_values(child)


def repository_markdown_documents(root):
    git_environment = {
        **os.environ,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
    }
    git_command = ("git", "-c", "core.fsmonitor=")
    repository_root_result = subprocess.run(
        (*git_command, "rev-parse", "--show-toplevel"),
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        env=git_environment,
    )
    resolved_root = root.resolve()
    repository_root = Path(
        os.fsdecode(repository_root_result.stdout.rstrip(b"\r\n"))
    ).resolve()
    if repository_root != resolved_root:
        raise ValueError(f"{root} must be the root of a Git working tree")

    inventory_result = subprocess.run(
        (
            *git_command,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ),
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        env=git_environment,
    )
    documents = set()
    for encoded_path in inventory_result.stdout.split(b"\0"):
        if not encoded_path:
            continue

        relative_path = Path(os.fsdecode(encoded_path))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Git returned an unsafe repository path: {relative_path}")
        if relative_path.suffix != ".md":
            continue

        document = root / relative_path
        if not document.is_file():
            continue
        try:
            document.resolve().relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(f"{document} resolves outside {root}") from error
        documents.add(document)

    return sorted(documents)


def yaml_scalar_error(path, line_number, key):
    return ValueError(f"{path}:{line_number} must use a supported string for {key!r}")


def yaml_scalar_tail_is_supported(tail):
    return not tail or not tail.strip(" \t") or re.fullmatch(r"[ \t]+#.*", tail)


def parse_single_quoted_yaml_string(path, line_number, key, value):
    result = []
    index = 1
    while index < len(value):
        character = value[index]
        if character != "'":
            result.append(character)
            index += 1
            continue

        if index + 1 < len(value) and value[index + 1] == "'":
            result.append("'")
            index += 2
            continue

        if not yaml_scalar_tail_is_supported(value[index + 1 :]):
            raise yaml_scalar_error(path, line_number, key)
        return "".join(result)

    raise yaml_scalar_error(path, line_number, key)


def parse_yaml_string(path, line_number, key, value):
    if value.startswith('"'):
        try:
            parsed_value, end = json.JSONDecoder().raw_decode(value)
        except json.JSONDecodeError as error:
            raise yaml_scalar_error(path, line_number, key) from error
        if not isinstance(parsed_value, str) or not yaml_scalar_tail_is_supported(
            value[end:]
        ):
            raise yaml_scalar_error(path, line_number, key)
        return parsed_value

    if value.startswith("'"):
        return parse_single_quoted_yaml_string(path, line_number, key, value)

    comment_start = next(
        (
            index
            for index, character in enumerate(value)
            if character == "#" and index > 0 and value[index - 1].isspace()
        ),
        len(value),
    )
    parsed_value = value[:comment_start].rstrip()
    if (
        not parsed_value
        or not (parsed_value[0].isalpha() or parsed_value[0] == "_")
        or parsed_value.casefold() in YAML_NON_STRING_SCALARS
        or re.search(r":(?:\s|$)", parsed_value)
    ):
        raise yaml_scalar_error(path, line_number, key)
    return parsed_value


def markdown_leading_indentation(line):
    width = 0
    index = 0
    while index < len(line) and line[index] in " \t":
        if line[index] == "\t":
            width += 4 - (width % 4)
        else:
            width += 1
        index += 1
    return width, index


def mask_markdown_code(markdown):
    characters = list(markdown)
    fence_character = None
    fence_length = 0
    in_indented_code = False
    may_start_indented_code = True
    offset = 0

    for line in markdown.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        is_blank = not content.strip(" \t")
        indentation, content_start = markdown_leading_indentation(content)
        stripped = content[content_start:]
        marker_length = 0
        if indentation <= 3 and stripped and stripped[0] in "`~":
            marker_length = len(stripped) - len(stripped.lstrip(stripped[0]))

        is_fence = marker_length >= 3
        if fence_character is not None:
            characters[offset : offset + len(content)] = " " * len(content)
            if (
                is_fence
                and stripped[0] == fence_character
                and marker_length >= fence_length
                and not stripped[marker_length:].strip(" \t")
            ):
                fence_character = None
                fence_length = 0
                may_start_indented_code = True
        else:
            if in_indented_code and not is_blank and indentation < 4:
                in_indented_code = False

            if in_indented_code or (
                not is_blank and indentation >= 4 and may_start_indented_code
            ):
                in_indented_code = True
                characters[offset : offset + len(content)] = " " * len(content)
            elif is_fence and not (
                stripped[0] == "`" and "`" in stripped[marker_length:]
            ):
                fence_character = stripped[0]
                fence_length = marker_length
                characters[offset : offset + len(content)] = " " * len(content)
            else:
                may_start_indented_code = is_blank

        offset += len(line)

    masked = "".join(characters)
    characters = list(masked)
    index = 0
    while index < len(masked):
        if masked[index] != "`" or markdown_character_is_escaped(masked, index):
            index += 1
            continue

        delimiter_length = len(masked[index:]) - len(masked[index:].lstrip("`"))
        search_index = index + delimiter_length
        closing_index = None
        while search_index < len(masked):
            next_backtick = masked.find("`", search_index)
            if next_backtick < 0:
                break
            run_length = len(masked[next_backtick:]) - len(
                masked[next_backtick:].lstrip("`")
            )
            if run_length == delimiter_length:
                closing_index = next_backtick
                break
            search_index = next_backtick + run_length

        if closing_index is None:
            index += delimiter_length
            continue

        end = closing_index + delimiter_length
        for character_index in range(index, end):
            if characters[character_index] not in "\r\n":
                characters[character_index] = " "
        index = end

    return "".join(characters)


def mask_markdown_html_comments(markdown):
    characters = list(markdown)
    index = 0
    while index < len(markdown):
        opening_index = markdown.find("<!--", index)
        if opening_index < 0:
            break
        closing_index = markdown.find("-->", opening_index + 4)
        end = len(markdown) if closing_index < 0 else closing_index + 3
        for character_index in range(opening_index, end):
            if characters[character_index] not in "\r\n":
                characters[character_index] = " "
        index = end
    return "".join(characters)


def markdown_character_is_escaped(markdown, index):
    backslashes = 0
    index -= 1
    while index >= 0 and markdown[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def skip_markdown_whitespace(markdown, index):
    line_endings = 0
    while index < len(markdown):
        if markdown[index] in " \t":
            index += 1
            continue
        if markdown[index] == "\r":
            index += 1
            if index < len(markdown) and markdown[index] == "\n":
                index += 1
        elif markdown[index] == "\n":
            index += 1
        else:
            break
        line_endings += 1
        if line_endings > 1:
            return None
    return index


def find_markdown_title_end(markdown, index):
    closing_character = {"\"": "\"", "'": "'", "(": ")"}.get(markdown[index])
    if closing_character is None:
        return None

    index += 1
    title_start = index
    while index < len(markdown):
        if markdown[index] == "\\" and index + 1 < len(markdown):
            index += 2
            continue
        if markdown[index] == closing_character:
            if re.search(
                r"(?:\r\n?|\n)[ \t]*(?:\r\n?|\n)",
                markdown[title_start:index],
            ):
                return None
            return index + 1
        index += 1
    return None


def parse_markdown_link_destination(markdown, opening_parenthesis):
    index = skip_markdown_whitespace(markdown, opening_parenthesis + 1)
    if index is None:
        return None
    destination_start = index

    if index < len(markdown) and markdown[index] == "<":
        index += 1
        destination_start = index
        while index < len(markdown):
            if markdown[index] == "\\" and index + 1 < len(markdown):
                index += 2
                continue
            if markdown[index] == ">":
                destination = markdown[destination_start:index]
                index += 1
                break
            if markdown[index] in "<\r\n":
                return None
            index += 1
        else:
            return None
    else:
        depth = 0
        while index < len(markdown):
            character = markdown[index]
            if character == "\\" and index + 1 < len(markdown):
                index += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    destination = markdown[destination_start:index]
                    return destination, index + 1
                depth -= 1
            elif character in " \t\r\n":
                if depth:
                    return None
                break
            elif character == "<":
                return None
            index += 1
        else:
            return None

        if depth:
            return None
        destination = markdown[destination_start:index]

    index = skip_markdown_whitespace(markdown, index)
    if index is None:
        return None
    if index < len(markdown) and markdown[index] == ")":
        return destination, index + 1
    if index >= len(markdown):
        return None

    title_end = find_markdown_title_end(markdown, index)
    if title_end is None:
        return None
    index = skip_markdown_whitespace(markdown, title_end)
    if index is None:
        return None
    if index >= len(markdown) or markdown[index] != ")":
        return None
    return destination, index + 1


def normalize_markdown_destination(destination):
    unescaped = MARKDOWN_ESCAPED_PUNCTUATION_PATTERN.sub(r"\1", destination)
    return html.unescape(unescaped)


def iter_markdown_link_destinations(markdown):
    markdown = mask_markdown_html_comments(mask_markdown_code(markdown))
    label_stack = []
    index = 0
    while index < len(markdown):
        if markdown_character_is_escaped(markdown, index):
            index += 1
            continue

        if markdown[index] == "[":
            is_image = (
                index > 0
                and markdown[index - 1] == "!"
                and not markdown_character_is_escaped(markdown, index - 1)
            )
            label_stack.append([index, False, is_image])
            index += 1
            continue

        if markdown[index] != "]" or not label_stack:
            index += 1
            continue

        _, contains_link, is_image = label_stack.pop()
        if contains_link or index + 1 >= len(markdown) or markdown[index + 1] != "(":
            index += 1
            continue

        parsed_link = parse_markdown_link_destination(markdown, index + 1)
        if parsed_link is None:
            index += 1
            continue

        destination, index = parsed_link
        yield normalize_markdown_destination(destination)
        if not is_image:
            for label in label_stack:
                if not label[2]:
                    label[1] = True


def parse_front_matter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path} must start with YAML front matter")

    try:
        closing_delimiter = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{path} has unclosed YAML front matter") from error

    fields = {}
    current_mapping = None
    for line_number, line in enumerate(lines[1:closing_delimiter], start=2):
        if not line or line.lstrip().startswith("#"):
            continue

        if line[0].isspace():
            if current_mapping is None or not line.startswith("  "):
                raise ValueError(f"{path}:{line_number} has unsupported indentation")

            key, separator, value = line.strip().partition(":")
            if not separator:
                raise ValueError(f"{path}:{line_number} is not a key-value field")

            mapping = fields[current_mapping]
            if not isinstance(mapping, dict):
                raise ValueError(f"{path}:{line_number} has no mapping parent")
            key = key.strip()
            if key in mapping:
                raise ValueError(f"{path}:{line_number} repeats the {key!r} field")
            mapping[key] = parse_yaml_string(
                path,
                line_number,
                key,
                value.strip(),
            )
            continue

        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"{path}:{line_number} is not a key-value field")

        key = key.strip()
        value = value.strip()
        if key in fields:
            raise ValueError(f"{path}:{line_number} repeats the {key!r} field")
        if value:
            fields[key] = parse_yaml_string(path, line_number, key, value)
            current_mapping = None
        else:
            fields[key] = {}
            current_mapping = key

    body = "\n".join(lines[closing_delimiter + 1 :]).strip()
    return fields, body


def assert_path_is_inside(test_case, path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        test_case.fail(f"{path} resolves outside {parent}")


class RepositoryStructureTests(unittest.TestCase):
    def test_expected_repository_files_exist(self):
        expected_files = (
            ".agents/plugins/marketplace.json",
            ".codex-plugin/plugin.json",
            ".editorconfig",
            ".gitattributes",
            ".github/workflows/ci.yml",
            ".gitignore",
            "CONTRIBUTING.md",
            "LICENSE",
            "README.ja.md",
            "README.md",
            "SECURITY.md",
            "skills/japanese-nominalization-audit/SKILL.md",
            "tests/pyproject.toml",
            "tests/test_repository.py",
        )
        for relative_path in expected_files:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load_json(PLUGIN_MANIFEST_PATH)
        cls.marketplace = load_json(MARKETPLACE_PATH)

    def test_json_documents_are_objects_without_duplicate_keys(self):
        for path in (PLUGIN_MANIFEST_PATH, MARKETPLACE_PATH):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsInstance(load_json(path), dict)

    def test_plugin_manifest_has_the_required_identity(self):
        self.assertEqual(
            set(self.plugin),
            {
                "author",
                "description",
                "homepage",
                "interface",
                "keywords",
                "license",
                "name",
                "repository",
                "skills",
                "version",
            },
        )
        self.assertEqual(self.plugin["name"], "japanese-nominalization-audit")
        self.assertIsNotNone(NAME_PATTERN.fullmatch(self.plugin["name"]))
        self.assertLessEqual(len(self.plugin["name"]), 64)
        self.assertIsNotNone(SEMVER_PATTERN.fullmatch(self.plugin["version"]))
        self.assertEqual(self.plugin["license"], "Apache-2.0")
        self.assertEqual(
            self.plugin["repository"],
            "https://github.com/NotLeonian/japanese-nominalization-audit",
        )
        self.assertEqual(
            self.plugin["homepage"],
            "https://github.com/NotLeonian/japanese-nominalization-audit#readme",
        )

        for field in ("description", "homepage", "repository"):
            with self.subTest(field=field):
                self.assertIsInstance(self.plugin[field], str)
                self.assertTrue(self.plugin[field].strip())

        for field in ("homepage", "repository"):
            with self.subTest(field=field):
                parsed_url = urlsplit(self.plugin[field])
                self.assertEqual(parsed_url.scheme, "https")
                self.assertTrue(parsed_url.netloc)

        author = self.plugin["author"]
        self.assertEqual(set(author), {"name", "url"})
        self.assertIsInstance(author["name"], str)
        self.assertTrue(author["name"].strip())
        author_url = urlsplit(author["url"])
        self.assertEqual(author_url.scheme, "https")
        self.assertTrue(author_url.netloc)

        keywords = self.plugin["keywords"]
        self.assertIsInstance(keywords, list)
        self.assertTrue(keywords)
        self.assertTrue(
            all(isinstance(keyword, str) and keyword.strip() for keyword in keywords)
        )
        self.assertFalse(
            any("[TODO:" in value for value in iter_string_values(self.plugin))
        )

    def test_semver_validation_is_strict(self):
        for version in (
            "0.1.0",
            "1.0.0-alpha",
            "1.0.0-1alpha",
            "1.0.0-alpha.1+build.5",
        ):
            with self.subTest(valid_version=version):
                self.assertIsNotNone(SEMVER_PATTERN.fullmatch(version))

        for version in ("v1.2.3", "1.2", "1.0.0-01", "1.0.0-alpha..1"):
            with self.subTest(invalid_version=version):
                self.assertIsNone(SEMVER_PATTERN.fullmatch(version))

    def test_plugin_interface_has_supported_value_types(self):
        interface = self.plugin["interface"]
        self.assertEqual(
            set(interface),
            {
                "capabilities",
                "category",
                "defaultPrompt",
                "developerName",
                "displayName",
                "longDescription",
                "shortDescription",
            },
        )
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
        ):
            with self.subTest(field=field):
                self.assertIsInstance(interface[field], str)
                self.assertTrue(interface[field].strip())

        self.assertIsInstance(interface["capabilities"], list)
        self.assertTrue(
            all(
                isinstance(item, str) and item.strip()
                for item in interface["capabilities"]
            )
        )

        prompts = interface["defaultPrompt"]
        self.assertIsInstance(prompts, list)
        self.assertGreaterEqual(len(prompts), 1)
        self.assertLessEqual(len(prompts), 3)
        for prompt in prompts:
            self.assertIsInstance(prompt, str)
            self.assertTrue(prompt.strip())
            self.assertLessEqual(len(prompt), 128)
        self.assertTrue(any(f"${self.plugin['name']}" in prompt for prompt in prompts))

    def test_manifest_skills_path_is_local_and_exists(self):
        self.assertEqual(self.plugin["skills"], "./skills/")
        skills_path = Path(self.plugin["skills"])
        self.assertFalse(skills_path.is_absolute())

        resolved_path = (ROOT / skills_path).resolve()
        assert_path_is_inside(self, resolved_path, ROOT)
        self.assertEqual(resolved_path, (ROOT / "skills").resolve())
        self.assertTrue(resolved_path.is_dir())

    def test_marketplace_entry_matches_the_plugin_manifest(self):
        self.assertEqual(set(self.marketplace), {"interface", "name", "plugins"})
        self.assertEqual(set(self.marketplace["interface"]), {"displayName"})
        self.assertEqual(self.marketplace["name"], self.plugin["name"])
        entries = self.marketplace["plugins"]
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)

        entry = entries[0]
        self.assertEqual(set(entry), {"category", "name", "policy", "source"})
        self.assertEqual(entry["name"], self.plugin["name"])
        self.assertEqual(
            self.marketplace["interface"]["displayName"],
            self.plugin["interface"]["displayName"],
        )
        self.assertEqual(entry["category"], self.plugin["interface"]["category"])
        self.assertEqual(entry["source"], {"source": "local", "path": "./"})
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )

        source_path = (ROOT / entry["source"]["path"]).resolve()
        assert_path_is_inside(self, source_path, ROOT)
        self.assertEqual(source_path, ROOT.resolve())
        self.assertTrue((source_path / ".codex-plugin" / "plugin.json").is_file())


class SkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load_json(PLUGIN_MANIFEST_PATH)
        cls.skills_root = (ROOT / cls.plugin["skills"]).resolve()
        cls.skill_directories = sorted(
            path
            for path in cls.skills_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
        cls.skill_files = [path / "SKILL.md" for path in cls.skill_directories]

    def test_every_skill_directory_contains_a_definition(self):
        self.assertTrue(self.skill_directories)
        for skill_file in self.skill_files:
            with self.subTest(path=skill_file.relative_to(ROOT)):
                self.assertTrue(skill_file.is_file())

    def test_plugin_contains_one_discoverable_skill(self):
        self.assertEqual(len(self.skill_files), 1)
        skill_file = self.skill_files[0]
        fields, body = parse_front_matter(skill_file)

        self.assertEqual(
            set(fields),
            {"compatibility", "description", "metadata", "name"},
        )
        self.assertEqual(fields["name"], self.plugin["name"])
        self.assertEqual(fields["name"], skill_file.parent.name)
        self.assertIsNotNone(NAME_PATTERN.fullmatch(fields["name"]))
        self.assertLessEqual(len(fields["name"]), 64)
        self.assertTrue(fields["description"].strip())
        self.assertLessEqual(len(fields["description"]), 1024)
        self.assertNotRegex(fields["description"], r"[<>]")
        self.assertTrue(fields["compatibility"].strip())
        self.assertEqual(set(fields["metadata"]), {"version"})
        self.assertIsNotNone(SEMVER_PATTERN.fullmatch(fields["metadata"]["version"]))
        self.assertTrue(body)

        version_match = SKILL_VERSION_PATTERN.search(
            skill_file.read_text(encoding="utf-8")
        )
        if version_match is None:
            self.fail("skill metadata must contain a quoted version")
        self.assertIsNotNone(SEMVER_PATTERN.fullmatch(version_match.group(1)))

    def test_yaml_string_subset_accepts_supported_scalar_syntax(self):
        cases = {
            r'"quoted \"value\""': 'quoted "value"',
            '"1.2.0" # version': "1.2.0",
            "'It''s valid'": "It's valid",
            "English prose # explanation": "English prose",
            "C# remains plain text": "C# remains plain text",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    parse_yaml_string(Path("SKILL.md"), 2, "description", value),
                    expected,
                )

    def test_yaml_string_subset_rejects_unsupported_scalar_syntax(self):
        values = (
            '"unfinished',
            "'unfinished",
            '"finished" trailing',
            "'finished' trailing",
            r'"bad \q"',
            "42",
            "2026-08-06",
            "true",
            "null",
            "[one]",
            "{key: value}",
            "|",
            ">",
            "&anchor value",
            "*anchor",
            "!tag value",
            "text: nested",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_yaml_string(Path("SKILL.md"), 2, "description", value)

    def test_skill_preserves_the_nominalization_audit_contract(self):
        _, body = parse_front_matter(self.skill_files[0])
        normalized_body = " ".join(body.split())

        required_statements = (
            (
                "Write Japanese technical prose without inventing compact noun "
                "expressions that readers must decode."
            ),
            "When evidence is inconclusive, prefer a clause over a new noun.",
            "Never resolve nominalization by deleting technical information.",
            "Do not review only the text added by the current change.",
            (
                "Do not claim a repository-wide audit unless the repository-wide "
                "first-party documentation set was actually examined."
            ),
            (
                "Keep the cleanup restricted to nominalization and noun-chain "
                "problems. Do not turn the audit into a general prose rewrite."
            ),
        )
        for statement in required_statements:
            with self.subTest(statement=statement):
                self.assertIn(statement, normalized_body)

    def test_skill_preserves_the_untranslated_term_rule(self):
        _, body = parse_front_matter(self.skill_files[0])
        normalized_body = " ".join(body.split())

        required_statements = (
            (
                "When a technical term has no established Japanese translation, "
                "do not simply transliterate the source-language term into katakana."
            ),
            (
                "Consider retaining the term in its original language, especially "
                "when that form is established or avoids ambiguity."
            ),
            (
                "Do not replace established katakana terminology solely because an "
                "original-language form also exists."
            ),
        )
        for statement in required_statements:
            with self.subTest(statement=statement):
                self.assertIn(statement, normalized_body)

    def test_skill_preserves_protected_material_and_reporting_requirements(self):
        _, body = parse_front_matter(self.skill_files[0])
        normalized_body = " ".join(body.split())

        required_statements = (
            "Do not rewrite the following solely to satisfy this skill:",
            "technical meaning, compatibility constraints, and defined terminology",
            "which documentation areas were audited;",
            "representative expressions that were expanded or intentionally retained;",
            "any unresolved or out-of-scope findings.",
        )
        for statement in required_statements:
            with self.subTest(statement=statement):
                self.assertIn(statement, normalized_body)


class DocumentationTests(unittest.TestCase):
    def test_document_inventory_uses_git_ignored_boundaries(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subprocess.run(
                ("git", "init", "--quiet"),
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            (root / ".gitignore").write_text(
                ".venv/\nvenv/\nenv/\n.tox/\n",
                encoding="utf-8",
            )
            repository_documents = (
                root / "README.md",
                root / ".github" / "PULL_REQUEST_TEMPLATE.md",
                root / "docs" / "setup" / "guide.md",
                root / "skills" / "example" / "SKILL.md",
            )
            environment_documents = (
                root / ".venv" / "package" / "README.md",
                root / "venv" / "package" / "README.md",
                root / "env" / "package" / "README.md",
                root / ".tox" / "package" / "README.md",
            )
            for document in (*repository_documents, *environment_documents):
                document.parent.mkdir(parents=True, exist_ok=True)
                document.write_text("[missing](not-installed.md)\n", encoding="utf-8")

            self.assertEqual(
                repository_markdown_documents(root),
                sorted(repository_documents),
            )

    def test_markdown_link_parser_handles_destinations_and_literal_code(self):
        markdown = r"""
[nested](docs/setup(legacy).md)
[title](docs/setup(legacy).md "Legacy setup")
[angle](<docs/setup (legacy).md> 'Legacy setup')
[escaped](docs/setup\(legacy\).md)
![image](images/diagram(legacy).png)
`[inline code](missing-inline.md)`
``[longer code span](missing-longer.md)``
\[escaped label](missing-escaped.md)
```text
[fenced](missing-fenced.md)
```
~~~
[tilde fenced](missing-tilde.md)
~~~
````
```
[inside long fence](missing-long-fence.md)
```
````
` unmatched [real](ok.md)

    [indented code](missing-indented.md)
\t[tab-indented code](missing-tab.md)

paragraph
    [paragraph continuation](continuation.md)
<!-- [comment](missing-comment.md) -->
[outer [inner](inner.md)](missing-outer.md)
[not a link](

missing-blank-line.md)
[multiline title](docs/multiline.md "first
second")
"""
        markdown = markdown.replace(
            r"\t[tab-indented code]",
            "\t[tab-indented code]",
        )
        self.assertEqual(
            list(iter_markdown_link_destinations(markdown)),
            [
                "docs/setup(legacy).md",
                "docs/setup(legacy).md",
                "docs/setup (legacy).md",
                "docs/setup(legacy).md",
                "images/diagram(legacy).png",
                "ok.md",
                "continuation.md",
                "inner.md",
                "docs/multiline.md",
            ],
        )

    def test_local_markdown_links_resolve_inside_the_repository(self):
        documents = repository_markdown_documents(ROOT)
        self.assertTrue(documents)

        for document in documents:
            text = document.read_text(encoding="utf-8")
            for target in iter_markdown_link_destinations(text):
                parsed_target = urlsplit(target)
                if parsed_target.scheme or target.startswith(("#", "//")):
                    continue

                relative_path = unquote(parsed_target.path)
                if not relative_path:
                    continue

                resolved_path = (document.parent / relative_path).resolve()
                with self.subTest(
                    document=document.relative_to(ROOT),
                    target=target,
                ):
                    assert_path_is_inside(self, resolved_path, ROOT)
                    self.assertTrue(resolved_path.exists())

    def test_readmes_and_workflow_use_the_same_test_command(self):
        for path in (
            ROOT / "README.md",
            ROOT / "README.ja.md",
            ROOT / "CONTRIBUTING.md",
            WORKFLOW_PATH,
        ):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(TEST_COMMAND, path.read_text(encoding="utf-8"))

    def test_contributing_documents_the_python_checks(self):
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        for command in PYTHON_CHECK_COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, contributing)

    def test_documentation_language_policy(self):
        japanese_documents = {
            ROOT / "README.ja.md",
            ROOT / "skills" / "japanese-nominalization-audit" / "SKILL.md",
        }
        documents = set(repository_markdown_documents(ROOT))
        english_documents = sorted(documents - japanese_documents)
        self.assertTrue(english_documents)

        for path in english_documents:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(
                    JAPANESE_CHARACTER_PATTERN.search(path.read_text(encoding="utf-8"))
                )

        self.assertIsNotNone(
            HIRAGANA_PATTERN.search((ROOT / "README.ja.md").read_text(encoding="utf-8"))
        )

    def test_readmes_link_to_each_other(self):
        self.assertIn(
            "[Japanese](README.ja.md)",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "[English](README.md)",
            (ROOT / "README.ja.md").read_text(encoding="utf-8"),
        )

    def test_python_check_configuration_targets_python_3_13(self):
        with PYPROJECT_PATH.open("rb") as file:
            config = tomllib.load(file)

        tools = config["tool"]
        self.assertEqual(tools["mypy"]["python_version"], "3.13")
        self.assertEqual(tools["pyright"]["pythonVersion"], "3.13")
        self.assertEqual(tools["ruff"]["target-version"], "py313")
        self.assertEqual(tools["ruff"]["format"]["quote-style"], "preserve")
        self.assertEqual(tools["ruff"]["lint"]["extend-select"], ["I"])

    def test_workflow_covers_supported_operating_systems(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        runner_matrix = "\n".join(
            f"          - {runner}" for runner in SUPPORTED_CI_RUNNERS
        )
        self.assertIn(runner_matrix, workflow)

        self.assertIn("uses: actions/setup-python@v6", workflow)
        self.assertIn('python-version: "3.13"', workflow)


if __name__ == "__main__":
    unittest.main()
