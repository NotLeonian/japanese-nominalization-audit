import json
import os
import re
import subprocess
import tomllib
import unicodedata
import unittest
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST_PATH = ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = ROOT / ".agents" / "plugins" / "marketplace.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = ROOT / "tests" / "pyproject.toml"
REQUIREMENTS_PATH = ROOT / "tests" / "requirements.txt"
TEST_COMMAND = "python -B -m unittest discover -s tests -p 'test_*.py' -v"
TEST_DEPENDENCY_COMMAND = (
    "python -m pip install --disable-pip-version-check -r tests/requirements.txt"
)
PYTHON_CHECK_COMMANDS = (
    "ruff format --check --config tests/pyproject.toml tests/test_repository.py",
    "ruff check --config tests/pyproject.toml tests/test_repository.py",
    "mypy --config-file tests/pyproject.toml tests/test_repository.py",
    "pyright --project tests/pyproject.toml tests/test_repository.py",
)
SUPPORTED_CI_RUNNERS = ("windows-latest", "macos-latest", "ubuntu-latest")
MARKDOWN_DOCUMENT_SUFFIXES = frozenset({".md", ".markdown"})
GITHUB_SOURCE_LINE_FRAGMENT_PATTERN = re.compile(r"L([0-9]+)(?:-L([0-9]+))?\Z")

NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
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
        if relative_path.suffix.casefold() not in MARKDOWN_DOCUMENT_SUFFIXES:
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


MARKDOWN_PARSER = MarkdownIt("commonmark")


@dataclass(frozen=True)
class MarkdownDestination:
    target: str
    is_hyperlink: bool


class MarkdownDestinationHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.destinations: list[MarkdownDestination] = []
        self.anchors: set[str] = set()

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        for name, value in attrs:
            if value and tag == "a" and name == "name":
                self.anchors.add(value)

        destination_attribute = {
            "a": "href",
            "img": "src",
        }.get(tag)
        if destination_attribute is None:
            return

        for name, value in attrs:
            if name != destination_attribute:
                continue
            if value is not None:
                self.destinations.append(
                    MarkdownDestination(
                        target=value,
                        is_hyperlink=tag == "a",
                    )
                )
            return


def iter_markdown_destinations(markdown):
    environment = {}
    for token in MARKDOWN_PARSER.parse(markdown, environment):
        if token.type not in {"html_block", "inline"}:
            continue

        parser = MarkdownDestinationHTMLParser()
        parser.feed(
            MARKDOWN_PARSER.renderer.render(
                [token],
                MARKDOWN_PARSER.options,
                environment,
            )
        )
        parser.close()
        yield from parser.destinations


def iter_markdown_link_destinations(markdown):
    for destination in iter_markdown_destinations(markdown):
        yield destination.target


def markdown_inline_text(tokens):
    parts = []
    for token in tokens:
        if token.type in {"code_inline", "text"}:
            parts.append(token.content)
        elif token.type in {"hardbreak", "softbreak"}:
            parts.append("\n")
    return "".join(parts)


def github_heading_slug(value):
    slug_characters = []
    for character in value.lower():
        category = unicodedata.category(character)
        if character == " ":
            slug_characters.append("-")
        elif (
            character == "-"
            or category[0] in {"L", "M"}
            or category
            in {
                "Nd",
                "Nl",
                "Pc",
            }
        ):
            slug_characters.append(character)
    return "".join(slug_characters)


class GitHubHeadingSlugger:
    def __init__(self):
        self.occurrences = {}

    def slug(self, value):
        original_slug = github_heading_slug(value)
        result = original_slug
        count = self.occurrences.get(original_slug, 0)
        while result in self.occurrences:
            count += 1
            result = f"{original_slug}-{count}"
        self.occurrences[original_slug] = count
        self.occurrences[result] = 0
        return result


def markdown_document_anchors(markdown):
    environment = {}
    tokens = MARKDOWN_PARSER.parse(markdown, environment)
    slugger = GitHubHeadingSlugger()
    anchors = set()

    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline_token = tokens[index + 1]
            if inline_token.type == "inline" and inline_token.children is not None:
                slug = slugger.slug(markdown_inline_text(inline_token.children))
                if slug:
                    anchors.add(slug)

        if token.type not in {"html_block", "inline"}:
            continue
        parser = MarkdownDestinationHTMLParser()
        parser.feed(
            MARKDOWN_PARSER.renderer.render(
                [token],
                MARKDOWN_PARSER.options,
                environment,
            )
        )
        parser.close()
        anchors.update(parser.anchors)

    return anchors


def resolve_markdown_local_path(document, repository_root, target):
    parsed_target = urlsplit(target)
    if parsed_target.scheme or parsed_target.netloc:
        return None

    decoded_path = unquote(parsed_target.path)
    if not decoded_path:
        if parsed_target.fragment:
            return document.resolve()
        return None

    if decoded_path.startswith("/"):
        return (repository_root / decoded_path.lstrip("/")).resolve()
    return (document.parent / decoded_path).resolve()


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


def assert_local_markdown_links_resolve(test_case, documents, repository_root):
    anchors_by_document = {}
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for destination in iter_markdown_destinations(text):
            resolved_path = resolve_markdown_local_path(
                document,
                repository_root,
                destination.target,
            )
            if resolved_path is None:
                continue

            assert_path_is_inside(test_case, resolved_path, repository_root)
            test_case.assertTrue(
                resolved_path.exists(),
                (
                    f"{destination.target!r} in "
                    f"{document.relative_to(repository_root)} does not exist"
                ),
            )

            parsed_target = urlsplit(destination.target)
            raw_fragment = parsed_target.fragment
            decoded_fragment = unquote(raw_fragment)
            fragment_candidates = {raw_fragment, decoded_fragment}
            if (
                not destination.is_hyperlink
                or not raw_fragment
                or any(fragment.casefold() == "top" for fragment in fragment_candidates)
                or any(":~:text=" in fragment for fragment in fragment_candidates)
                or not resolved_path.is_file()
                or resolved_path.suffix.casefold() not in MARKDOWN_DOCUMENT_SUFFIXES
            ):
                continue

            plain_values = parse_qs(
                parsed_target.query,
                keep_blank_values=True,
            ).get("plain", [])
            if "1" in plain_values:
                source_line_match = GITHUB_SOURCE_LINE_FRAGMENT_PATTERN.fullmatch(
                    decoded_fragment
                )
                if source_line_match is None:
                    test_case.fail(
                        f"{destination.target!r} in "
                        f"{document.relative_to(repository_root)} does not use a "
                        "GitHub source line fragment"
                    )
                    continue
                first_line = int(source_line_match.group(1))
                last_line_group = source_line_match.group(2)
                last_line = (
                    int(last_line_group) if last_line_group is not None else first_line
                )
                line_count = len(resolved_path.read_text(encoding="utf-8").splitlines())
                test_case.assertTrue(
                    1 <= first_line <= last_line <= line_count,
                    (
                        f"{destination.target!r} in "
                        f"{document.relative_to(repository_root)} refers outside "
                        f"the {line_count} source lines in "
                        f"{resolved_path.relative_to(repository_root)}"
                    ),
                )
                continue

            anchors = anchors_by_document.get(resolved_path)
            if anchors is None:
                anchors = markdown_document_anchors(
                    resolved_path.read_text(encoding="utf-8")
                )
                anchors_by_document[resolved_path] = anchors
            test_case.assertTrue(
                anchors.intersection(fragment_candidates),
                (
                    f"{destination.target!r} in "
                    f"{document.relative_to(repository_root)} does not match "
                    f"an anchor in {resolved_path.relative_to(repository_root)}"
                ),
            )


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
            "tests/requirements.txt",
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

        non_ascii_digit = "\N{ARABIC-INDIC DIGIT TWO}"
        for version in (
            "v1.2.3",
            "1.2",
            "1.0.0-01",
            "1.0.0-alpha..1",
            f"1{non_ascii_digit}.0.0",
            f"1.1{non_ascii_digit}.0",
            f"1.0.1{non_ascii_digit}",
            f"1.0.0-1{non_ascii_digit}",
            f"1.0.0-{non_ascii_digit}alpha",
            f"1.0.0-alpha.1{non_ascii_digit}",
            f"1.0.0-alpha.{non_ascii_digit}beta",
        ):
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
                root / ".venv" / "package" / "README.MD",
                root / "venv" / "package" / "guide.markdown",
                root / "env" / "package" / "notes.MarkDown",
                root / ".tox" / "package" / "README.md",
            )
            for document in (*repository_documents, *environment_documents):
                document.parent.mkdir(parents=True, exist_ok=True)
                document.write_text("[missing](not-installed.md)\n", encoding="utf-8")

            self.assertEqual(
                repository_markdown_documents(root),
                sorted(repository_documents),
            )

    def test_document_inventory_supports_common_markdown_suffixes(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subprocess.run(
                ("git", "init", "--quiet"),
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            supported_documents = (
                root / "uppercase" / "README.MD",
                root / "long-form" / "guide.markdown",
                root / "mixed-case" / "notes.MarkDown",
            )
            unsupported_documents = (
                root / "docs" / "guide.mdx",
                root / "docs" / "guide.md.txt",
                root / "README",
            )
            for document in (*supported_documents, *unsupported_documents):
                document.parent.mkdir(parents=True, exist_ok=True)
                document.write_text("[missing](not-installed.md)\n", encoding="utf-8")

            subprocess.run(
                (
                    "git",
                    "add",
                    "--",
                    os.fspath(supported_documents[0].relative_to(root)),
                ),
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )

            self.assertEqual(
                repository_markdown_documents(root),
                sorted(supported_documents),
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
                "docs/setup%20(legacy).md",
                "docs/setup(legacy).md",
                "images/diagram(legacy).png",
                "ok.md",
                "continuation.md",
                "inner.md",
                "docs/multiline.md",
            ],
        )

    def test_markdown_link_parser_resolves_reference_links(self):
        markdown = """
[full][setup]
[collapsed][]
[shortcut]
![diagram][asset]

[setup]: docs/full.md "Setup"
[collapsed]: docs/collapsed.md
[shortcut]: docs/shortcut.md
[asset]: images/diagram.png
"""
        self.assertEqual(
            list(iter_markdown_link_destinations(markdown)),
            [
                "docs/full.md",
                "docs/collapsed.md",
                "docs/shortcut.md",
                "images/diagram.png",
            ],
        )

    def test_markdown_link_parser_inspects_raw_html_links_and_images(self):
        markdown = """
<a href="docs/block.html">block link</a>
<img src="images/block.png" alt="Block image">

Inline <A HREF=docs/inline.html>link</A> and
<IMG SRC=images/inline.png ALT="Inline image">.

<!-- <a href="missing-comment.html">comment example</a> -->
`<img src="missing-code.png">`
```html
<a href="missing-fence.html">fenced example</a>
```

<script><a href="missing-script.html">script example</a></script>
<style><a href="missing-style.html">style example</a></style>
<textarea><img src="missing-textarea.png"></textarea>

[Markdown link](docs/markdown.md)
![Markdown image](images/markdown.png)
"""
        self.assertEqual(
            list(iter_markdown_link_destinations(markdown)),
            [
                "docs/block.html",
                "images/block.png",
                "docs/inline.html",
                "images/inline.png",
                "docs/markdown.md",
                "images/markdown.png",
            ],
        )

    def test_markdown_link_parser_ignores_raw_html_literal_blocks(self):
        for tag in ("pre", "script", "style", "textarea"):
            with self.subTest(tag=tag):
                markdown = f"""<{tag} data-example="true">
[example](missing.md)
</{tag}>
[outside](outside.md)
"""
                self.assertEqual(
                    list(iter_markdown_link_destinations(markdown)),
                    ["outside.md"],
                )

        self.assertEqual(
            list(
                iter_markdown_link_destinations(
                    "<SCRIPT>\n[example](missing.md)\n"
                    "</style> [same line](missing-suffix.md)\n"
                    "[outside](outside.md)\n"
                )
            ),
            ["outside.md"],
        )
        self.assertEqual(
            list(
                iter_markdown_link_destinations(
                    "prefix <pre>[inline](inside.md)</pre>\n"
                )
            ),
            ["inside.md"],
        )
        self.assertEqual(
            list(
                iter_markdown_link_destinations(
                    "- <pre>\n  [example](missing.md)\n- [outside](outside.md)\n"
                )
            ),
            ["outside.md"],
        )

    def test_markdown_link_parser_preserves_markdown_boundaries(self):
        markdown = """
> ```text
> [code][missing]
> ```

- <pre>
  [example](missing.md)
  </pre>

[text <span data-example="][missing]">
[invalid](<span>suffix)
[outside](outside.md)

[missing]: missing.md
"""
        self.assertEqual(
            list(iter_markdown_link_destinations(markdown)),
            ["outside.md"],
        )

    def test_markdown_document_anchors_follow_github_heading_rules(self):
        markdown = """
# Testing
## Markup *and* `code`: 日本語!

Setext Heading
==============

## Echo
## Echo
## Echo-1
## Echo
###### Level Six
## ![Architecture](diagram.svg) Diagram
## Before ![Architecture](diagram.svg) After
## Diagram ![Architecture](diagram.svg)
## 😄 Emoji
## Привет non-latin 你好

<a name="custom anchor"></a>
<a name="literal%20anchor"></a>
<script id="script-id"><a name="script-anchor"></a></script>
<iframe id="iframe-id"></iframe>
<textarea id="textarea-id"></textarea>

`<a name="code-anchor"></a>`
<!-- <span id="comment-anchor"></span> -->
"""
        self.assertEqual(
            markdown_document_anchors(markdown),
            {
                "-diagram",
                "-emoji",
                "before--after",
                "custom anchor",
                "diagram-",
                "echo",
                "echo-1",
                "echo-1-1",
                "echo-2",
                "level-six",
                "literal%20anchor",
                "markup-and-code-日本語",
                "привет-non-latin-你好",
                "setext-heading",
                "testing",
            },
        )
        self.assertEqual(
            github_heading_slug(" Leading\tand punctuation! "),
            "-leadingand-punctuation-",
        )

    def test_local_markdown_paths_use_document_and_repository_roots(self):
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory).resolve()
            document = repository_root / "docs" / "guide.md"
            cases = (
                ("setup.md", document.parent / "setup.md"),
                ("../README.md", repository_root / "README.md"),
                ("/README.md?plain=1#readme", repository_root / "README.md"),
                ("/", repository_root),
                (
                    "/NotLeonian/japanese-nominalization-audit/issues",
                    repository_root
                    / "NotLeonian"
                    / "japanese-nominalization-audit"
                    / "issues",
                ),
                ("#section", document.resolve()),
                ("?plain=1", None),
                ("https://example.com/guide", None),
                ("//cdn.example.com/guide", None),
            )
            for target, expected in cases:
                with self.subTest(target=target):
                    self.assertEqual(
                        resolve_markdown_local_path(
                            document,
                            repository_root,
                            target,
                        ),
                        expected,
                    )

    def test_local_markdown_link_fragments_are_validated(self):
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory).resolve()
            document = repository_root / "guide.md"
            target_document = repository_root / "target.MD"
            asset = repository_root / "asset.svg"
            target_document.write_text(
                """# Target Section

## 日本語の見出し

<a name="custom anchor"></a>
<a name="literal%20anchor"></a>
""",
                encoding="utf-8",
            )
            asset.write_text('<svg id="symbol"></svg>\n', encoding="utf-8")
            document.write_text(
                """# Source Section

[fragment only](#source-section)
[cross-document](target.MD#target-section)
[repository root](/target.MD#target-section)
[encoded Unicode](target.MD#%E6%97%A5%E6%9C%AC%E8%AA%9E%E3%81%AE%E8%A6%8B%E5%87%BA%E3%81%97)
[custom anchor](target.MD#custom%20anchor)
[literal percent anchor](target.MD#literal%20anchor)
[document top](target.MD#TOP)
[source line](target.MD?plain=1#L2)
[source line range](target.MD?view=source&plain=%31#L1-L4)
[browser text fragment](target.MD#:~:text=Target%20Section)
[SVG fragment](asset.svg#symbol)
![image fragment](target.MD#not-a-heading)
<a href="target.MD#target-section">raw HTML link</a>
<img src="target.MD#not-a-heading" alt="raw HTML image">
[empty fragment](target.MD#)
""",
                encoding="utf-8",
            )

            assert_local_markdown_links_resolve(
                self,
                [document],
                repository_root,
            )

            broken_targets = (
                ("target.MD#tesing", "does not match"),
                ("#sorce-section", "does not match"),
                (
                    "target.MD?plain=1#target-section",
                    "does not use a GitHub source line fragment",
                ),
                ("target.MD?plain=1#L999", "refers outside"),
                ("target.MD?plain=1#L4-L2", "refers outside"),
            )
            for broken_target, error_pattern in broken_targets:
                with self.subTest(broken_target=broken_target):
                    document.write_text(
                        f"# Source Section\n\n[broken]({broken_target})\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(AssertionError, error_pattern):
                        assert_local_markdown_links_resolve(
                            self,
                            [document],
                            repository_root,
                        )

            document.write_text(
                '<a href="target.MD#tesing">broken raw HTML link</a>\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AssertionError, "does not match"):
                assert_local_markdown_links_resolve(
                    self,
                    [document],
                    repository_root,
                )

    def test_local_markdown_links_resolve_inside_the_repository(self):
        documents = repository_markdown_documents(ROOT)
        self.assertTrue(documents)
        assert_local_markdown_links_resolve(self, documents, ROOT)

    def test_readmes_and_workflow_use_the_same_test_command(self):
        for path in (
            ROOT / "README.md",
            ROOT / "README.ja.md",
            ROOT / "CONTRIBUTING.md",
            WORKFLOW_PATH,
        ):
            contents = path.read_text(encoding="utf-8")
            for command in (TEST_DEPENDENCY_COMMAND, TEST_COMMAND):
                with self.subTest(path=path.relative_to(ROOT), command=command):
                    self.assertIn(command, contents)

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
        self.assertEqual(tools["pyright"]["venv"], ".venv")
        self.assertEqual(tools["pyright"]["venvPath"], "..")
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
        self.assertIn(TEST_DEPENDENCY_COMMAND, workflow)

    def test_workflow_avoids_duplicate_pull_request_branch_runs(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn(
            """on:
  pull_request:
  push:
    branches:
      - main
  workflow_dispatch:
""",
            workflow,
        )

    def test_test_dependencies_are_pinned(self):
        self.assertEqual(
            REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines(),
            [
                "markdown-it-py==4.2.0",
                "mdurl==0.1.2",
                "mypy==2.3.0",
                "pyright==1.1.411",
                "ruff==0.16.1",
            ],
        )


if __name__ == "__main__":
    unittest.main()
