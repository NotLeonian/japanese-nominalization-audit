# japanese-nominalization-audit

[Japanese](README.ja.md)

`japanese-nominalization-audit` is a Codex plugin containing an Agent Skill
for reviewing nominalization and compressed noun expressions in Japanese
technical documentation.

When the skill is active, it directs the agent to preserve events, states,
conditions, and causal relations as clauses instead of hiding them inside ad
hoc compound nouns.

## Behavior

The skill directs the agent to:

- inspect newly coined or weakly established compound nouns, excessive
  nominalization, and long noun sequences with unclear internal relations;
- distinguish established technical terms and useful project-defined terms
  from context-specific shorthand and accidental coinages;
- expand unclear nouns into clauses that retain the actor, action, state,
  object, timing, condition, negation, modality, and causal direction;
- reconsider headings, table labels, and bold lead-ins when their layout
  forces a complete explanation into an invented noun phrase;
- use project definitions and authoritative field evidence before deciding
  that a term is established;
- review relevant pre-existing first-party documentation as well as text
  added or modified by the current task; and
- report uncertain terms and findings that fall outside the permitted scope.

When a technical term has no established Japanese translation, the skill
directs the agent not to create a katakana transliteration merely to make the
term look localized. The original-language form should remain an option,
especially when it is established or less ambiguous. This is not a rule to
replace established katakana terminology.

Source code, identifiers, API names, configuration keys, schema fields,
commands, product names, formal standards, exact quotations, legal text, and
fixed interface wording remain protected. Renaming a public interface is a
separate compatibility decision.

## Installation

Clone the repository, register its absolute path as a local marketplace, and
install the plugin:

```console
git clone https://github.com/NotLeonian/japanese-nominalization-audit.git
codex plugin marketplace add /absolute/path/to/japanese-nominalization-audit
codex plugin add japanese-nominalization-audit@japanese-nominalization-audit
```

Start a new Codex thread after installation so that the skill is loaded.

To install only the skill, copy its `SKILL.md` into the local Agent Skills
directory:

```console
mkdir -p "$HOME/.agents/skills/japanese-nominalization-audit"
cp /absolute/path/to/japanese-nominalization-audit/skills/japanese-nominalization-audit/SKILL.md "$HOME/.agents/skills/japanese-nominalization-audit/SKILL.md"
```

## Usage

Invoke the skill while drafting or editing Japanese technical documentation:

```text
$japanese-nominalization-audit

Review the relevant Japanese documentation and repair unclear nominalization.
```

A compatible host may also select the skill automatically for Japanese
READMEs, specifications, ADRs, design documents, operational guides, release
notes, and explanatory comments when the task calls for this focused review.

The audit is not limited to the current diff. Unless the user sets a narrower
boundary, it also covers relevant neighboring documents, shared terminology,
templates, glossaries, and central documentation affected by the change.
Generated artifacts, vendored material, archived snapshots, and quotations
are excluded; when generated prose has a problem, edit its source when
possible.

## Limitations

`japanese-nominalization-audit` is an instruction for an agent, not a Japanese
parser, linter, dictionary, terminology authority, or proof of technical
correctness.

- It addresses nominalization and noun-chain problems only. It is not a
  general guide to Japanese style, tone, politeness, punctuation, document
  structure, proofreading, or translation.
- Candidate searches and regular expressions can miss problems and produce
  false positives. Every match must be read in context.
- Establishing a technical term requires project and field evidence. A single
  repository occurrence, repeated wording from one source, or an isolated
  search snippet is not enough.
- The skill cannot resolve an uncertain term reliably when definitions or
  authoritative sources are unavailable. It directs the agent to report the
  uncertainty instead of guessing.
- It does not prohibit katakana or require original-language spelling. It
  retains established katakana terms and questions only an unsupported new
  transliteration when no Japanese translation is established.
- It does not automatically redesign project terminology or rename public
  interfaces. Compatibility and defined terminology take priority.
- It does not rewrite protected code, identifiers, quotations, externally
  maintained text, legal text, or fixed messages solely for stylistic reasons.
- It cannot guarantee that every relevant expression has been found, that a
  rewrite is technically correct, or that readers in every field will make
  the same terminology judgment.
- It may broaden a documentation change to include clear, related findings in
  pre-existing first-party prose. A user-provided scope limit still controls
  which files may be edited.
- A repository-wide audit may be claimed only after all repository-wide
  first-party documentation in scope has actually been examined.
- It applies only while the host has loaded the skill and the agent follows
  it. It cannot control edits made by a user, IDE, another process, another
  agent, or another session.

The final report records the areas examined, files changed because of the
audit, representative wording that was expanded or retained, and unresolved
or out-of-scope findings. That report describes the performed review; it is
not a guarantee that no other issue exists.

## Verification

Validate the JSON files and inspect the Markdown and skill content before
publishing:

```console
python3 -m json.tool .codex-plugin/plugin.json
python3 -m json.tool .agents/plugins/marketplace.json
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
git diff --check
```

The plugin validator depends on Codex system skill files and their Python
dependencies. It is optional when those files are unavailable. It also checks
the bundled skill manifest.

Validation confirms the static plugin and skill structure. It does not
simulate an agent, establish Japanese terminology, or prove that an agent will
follow the skill correctly. Behavioral review should include both problematic
phrases and established terms that must remain unchanged.

## Testing

Run the repository test suite from the root of a Git working tree. The suite
uses Git and the Python packages pinned in `tests/requirements.txt`. Install
the packages before running the tests:

```console
python -m pip install --disable-pip-version-check -r tests/requirements.txt
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

The tests validate the JSON files, cross-check the plugin and marketplace
metadata, verify skill discovery and the core
`japanese-nominalization-audit` instructions, verify the Python check
configuration, and check local links in tracked and non-ignored untracked files
with `.md` or `.markdown` filename extensions throughout the working tree;
extension matching is case-insensitive. They validate the repository
structure and static instruction contract; they do not simulate an agent,
determine whether Japanese terminology is established, or prove that an agent
will follow the skill. Link parsing follows the CommonMark preset provided by
`markdown-it-py`; syntax that requires a separate Markdown extension is not
enabled.

For pushes and pull requests, the GitHub Actions workflow installs the pinned
packages and runs the same test suite on Windows, macOS, and Ubuntu with Python
3.13.

The contributor-facing Ruff, mypy, and Pyright commands are documented in
[CONTRIBUTING.md](CONTRIBUTING.md). The requirements file pins those tools as
well as the package used to parse Markdown.

## Repository Layout

```text
japanese-nominalization-audit/
├── .github/
│   └── workflows/
│       └── ci.yml
├── .agents/
│   └── plugins/
│       └── marketplace.json
├── .codex-plugin/
│   └── plugin.json
├── skills/
│   └── japanese-nominalization-audit/
│       └── SKILL.md
├── tests/
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── test_repository.py
├── .editorconfig
├── .gitattributes
├── .gitignore
├── CONTRIBUTING.md
├── LICENSE
├── README.ja.md
├── README.md
└── SECURITY.md
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md) for the security policy and reporting
instructions. Do not use this skill as a security or correctness boundary.

## License

Licensed under the [Apache License 2.0](LICENSE).
