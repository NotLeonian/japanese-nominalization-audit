# Contributing

Contributions to `japanese-nominalization-audit` are welcome.

## Scope

Keep changes focused on the plugin's purpose: detecting and repairing ad hoc
compound nouns, compressed noun chains, and excessive nominalization in
Japanese technical documentation.

Do not turn the skill into a general Japanese style guide, translation guide,
proofreader, terminology authority, or technical-correctness checker. Avoid
unrelated rewrites for tone, politeness, punctuation, vocabulary, or document
structure.

For substantial behavioral changes, open an issue before preparing a pull
request.

## Documentation and Language

`skills/japanese-nominalization-audit/SKILL.md` is the authoritative skill
definition.

When changing its behavior:

- update `README.md` and `README.ja.md` where necessary;
- preserve the same technical meaning in both READMEs;
- write all files except `README.ja.md` in English;
- retain Japanese expressions where they are examples, protected tokens, or
  necessary subject matter inside the skill definition; and
- keep the documented scope and limitations accurate.

The plugin manifest and the skill metadata have separate version scopes. Bump
the plugin version for packaging changes and the skill metadata version for
changes to its instruction contract. A change may require one or both.

## Terminology and Examples

Treat established terminology as an evidence question. Prefer, in order:

1. explicit project definitions and terminology decisions;
2. consistent first-party use in authoritative project documentation;
3. standards, vendor documentation, dictionaries, and respected field
   references; and
4. independent exact-phrase usage with the same technical meaning.

Do not use one repository occurrence or a context-free search result as proof
that a term is established. When no Japanese translation is established, do
not invent a katakana transliteration merely to localize the term. Consider
the original-language form, but retain katakana terminology that is already
established.

Add only independently authored examples or examples whose license clearly
permits reuse. Do not import distinctive example sets or explanatory wording
from an incompatible source.

## Testing Changes

Run the repository tests from the root of a Git working tree. The suite uses
the Python standard library and Git; it does not require third-party Python
packages:

```console
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

For pushes and pull requests, GitHub Actions runs the same suite on Windows,
macOS, and Ubuntu with Python 3.13. The suite validates the manifests, their
cross-file metadata, skill discovery, the core instruction contract, the
Python check configuration, and local documentation links. The link inventory
includes tracked Markdown and non-ignored untracked Markdown throughout the
working tree. The suite does not replace the behavioral checks below.

When Ruff, mypy, and Pyright are available, run the Python checks from the
repository root:

```console
ruff format --check --config tests/pyproject.toml tests/test_repository.py
ruff check --config tests/pyproject.toml tests/test_repository.py
mypy --config-file tests/pyproject.toml tests/test_repository.py
pyright --project tests/pyproject.toml tests/test_repository.py
```

These commands use the Python 3.13 settings in `tests/pyproject.toml`. To apply
formatting, omit `--check` from the first command.

Review behavioral changes against examples that cover:

- an accidental compound noun that hides an event or state;
- a long noun sequence with more than one plausible internal relationship;
- an established term that must remain unchanged;
- a project-defined term supported by authoritative documentation;
- a technical term without an established Japanese translation;
- a protected identifier or interface label;
- a user-imposed audit boundary; and
- an uncertain term that should be reported instead of rewritten.

Candidate-search examples in the skill are discovery aids, not automatic
classification tests. Always inspect the surrounding proposition and confirm
that a rewrite preserves the actor, object, condition, timing, negation,
modality, and causal direction.

For additional validation in a Codex installation that includes the system
skill scripts and their Python dependencies, run:

```console
python3 -m json.tool .codex-plugin/plugin.json
python3 -m json.tool .agents/plugins/marketplace.json
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
git diff --check
```

The plugin validator is optional because it depends on files outside this
repository. It assumes that the Codex system skills are installed in their
default location and also checks the bundled skill manifest.

For a local Codex test, register the repository as a marketplace and install
the plugin:

```console
codex plugin marketplace add /absolute/path/to/japanese-nominalization-audit
codex plugin add japanese-nominalization-audit@japanese-nominalization-audit
```

Start a new Codex thread before testing an updated installation.

## Pull Requests

A pull request should:

- explain the problem and the proposed behavior;
- identify changed limitations, terminology assumptions, or compatibility
  constraints;
- include documentation updates when behavior changes;
- describe the first-party documentation boundary used for any Japanese audit;
- distinguish clear corrections from uncertain or out-of-scope findings;
- avoid unrelated formatting or prose changes; and
- contain no generated or environment-specific files.

## License

By submitting a contribution, you agree that it may be distributed under the
[Apache License 2.0](LICENSE).
