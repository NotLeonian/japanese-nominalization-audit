---
name: japanese-nominalization-audit
description: Detect and repair ad hoc compound nouns, compressed noun chains, and excessive nominalization in Japanese technical documentation, including unclear mixtures of Japanese and alphanumeric tokens. Use only when the user explicitly selects this skill through the host's skill invocation mechanism; in Codex, invoke `$japanese-nominalization-audit`. Never infer invocation from an ordinary drafting or editing task, a potential finding, or a plain-language request to use the skill. This skill supplies audit criteria; the user's instructions determine when to audit and what to examine. Do not audit existing documents without the user's instruction. Keep the review narrowly focused on nominalization problems; this is not a general Japanese style guide and has no dependency on another writing skill.
compatibility: Intended for ChatGPT, Codex, and other Agent Skills-compatible agents. Repository search and exact-phrase usage checks are recommended when available.
metadata:
  version: "1.4.0"
---

# Japanese Nominalization Audit

## Invocation requirement

Apply this audit only when the user explicitly selects this skill through the host's skill invocation mechanism. In Codex, invoke `$japanese-nominalization-audit` in the prompt.

Do not infer authorization from drafting or editing Japanese prose, noticing a potential nominalization problem, or deciding that the audit would be useful. A plain-language request to use this skill does not count as explicit selection. Merely referring to, discussing, maintaining, installing, or configuring the skill does not select it. Without explicit selection through the host's skill invocation mechanism, do not inspect or modify prose under this skill.

This skill summarizes points to examine during an audit. It does not authorize the agent to decide when to audit or how far the audit extends without the user's instructions. Explicit selection makes the criteria available; it does not by itself authorize an audit of existing documents.

Do not audit existing documents without the user's instruction. Follow the user's requested timing, targets, and review or editing scope. If the intended timing or targets cannot be determined from the user's instructions, ask before starting the audit; do not choose documents or expand the scope on your own.

## Objective

Write Japanese technical prose without inventing compact noun expressions that readers must decode.

Many technical statements describe an event, state, omission, condition, or causal relation. Preserve that proposition as a clause when a noun would conceal who did what, what remains true, what was omitted, or under which condition the result occurs.

Use a compact technical noun when it is established in the relevant field or deliberately defined by the project. Do not treat a sequence of familiar kanji as established terminology merely because every component is familiar.

## Scope

This skill addresses only:

- newly coined or weakly established compound nouns;
- nominalization that suppresses an actor, action, state, timing, condition, negation, or causal direction;
- long noun sequences whose internal relationships are not explicit;
- short or long compounds that obscure relationships between Japanese words and Latin letters, digits, version strings, or symbols;
- headings, table labels, and bold lead-ins that force an explanation into an unnatural noun phrase.

Do not perform broad rewriting for tone, politeness, rhythm, punctuation, paragraph order, or vocabulary. Change those features only when required to resolve a problem listed above.

This skill is self-contained. Do not require a separate Japanese-writing or technical-writing skill before applying it.

## Decision rule

For every dense noun expression, determine which of the following applies:

1. **Established term** — The expression has a stable technical meaning supported by project definitions or reliable field usage. Retain it.
2. **Useful project term** — The project explicitly defines the expression, uses it consistently, and benefits from naming the concept. Retain it unless the task includes terminology redesign.
3. **Context-specific shorthand** — The expression is understandable only after reconstructing an unstated action or relationship. Expand it into a clause.
4. **Accidental coinage** — The expression was assembled to fill a heading, subject, bullet label, or table cell. Replace it with a sentence, clause, or clearer label.

When evidence is inconclusive, prefer a clause over a new noun.

## Patterns that require inspection

### Productive suffixes attached to an ad hoc base

Inspect expressions created by attaching elements such as `〜化`, `〜性`, `〜度`, `〜不足`, `〜残存`, `未〜`, or `非〜` to a base that is itself a long or novel combination.

Examples that should trigger review include:

- `認証情報残存性`
- `通知再送可能化`
- `設定読込未完了度`
- `応答遅延非検知化`

The suffix alone is not an error. Terms such as `冪等性`, `参照透過性`, `後方互換性`, `遅延評価`, `排他制御`, and `型推論` are established when used in their conventional senses.

### Nouns that replace an event

Inspect noun subjects followed by generic predicates such as `原因である`, `要因となる`, `重要である`, `必要となる`, or `引き起こす`.

Ask whether the subject is really an event that can be stated more directly:

- something remains stored;
- a process starts before another process finishes;
- a check was skipped;
- two components use different assumptions;
- a request arrives after a deadline.

If so, write the event with a verb and preserve the original causal direction.

### Unmarked noun sequences

Inspect long noun sequences that can express several different relationships: target, purpose, timing, possession, condition, cause, or result.

Candidates include:

- `監査ログ保存期間変更影響確認`
- `依存サービス応答遅延対応方針`
- `移行先データ形式差異調査結果`

Do not insert particles mechanically. First reconstruct the intended proposition, then choose a clause or a shorter, established label.

### Mixed Japanese and alphanumeric compounds

Inspect the whole expression even when Latin letters, digits, spaces, punctuation, or inline-code formatting interrupt the Japanese noun sequence. A candidate need not be long or consist entirely of kanji or katakana. Familiar product names, version numbers, and variable names do not establish the compound built around them.

Examples that should trigger review include:

- `LLVM 20 系`: determine which releases are meant. If the intended set is releases whose major version is 20, write `LLVM のメジャーバージョンが 20 のリリース`. Do not silently broaden the set to version 20 and later or narrow it to one particular release.
- `可変 y 範囲`: determine what `y` denotes, which range can change, and how it changes. For a graph whose displayed range can be changed, use wording such as `y 軸の表示範囲を変更できる`. Preserve any distinction between manual adjustment and automatic scaling; if the context does not resolve it, report the ambiguity rather than inventing behavior.

Preserve protected tokens such as `LLVM`, `20`, and `y` while clarifying their relationship to the surrounding Japanese. Adding spaces alone does not repair a hidden relationship. Mixed scripts alone are not a defect: retain established expressions such as `UTF-8`, `HTTP/2`, and `x 座標` when used in their conventional senses.

### Presentation structures that demand a noun

A heading, bold prefix, or two-column table can pressure the writer to compress a full explanation into a short label. Do not preserve that layout when it repeatedly produces invented terms.

For causes, conditions, and mechanisms, prefer complete clauses or sentences. Keep noun-only labels for actual categories, field names, commands, statuses, and established concepts.

## Evidence for established usage

Use the strongest available evidence in this order:

1. An explicit project glossary, specification, schema, or terminology decision.
2. Consistent first-party use across authoritative project documents.
3. Standards, vendor documentation, dictionaries, or respected field references.
4. Exact-phrase search results showing independent use with the same technical meaning.

Do not infer establishment from one repository occurrence, copied documentation, generated pages, search snippets without context, or repeated use within a single source.

When a technical term has no established Japanese translation, do not simply transliterate the source-language term into katakana. Consider retaining the term in its original language, especially when that form is established or avoids ambiguity. Do not replace established katakana terminology solely because an original-language form also exists.

Identifiers and public interfaces require additional care. Do not rename API fields, configuration keys, database columns, command names, UI labels, issue types, or public glossary entries merely because their Japanese wording is dense. Treat interface changes as a separate compatibility decision.

## Rewrite method

For each candidate:

1. State the hidden proposition in plain terms.
2. Identify the actor or subject, action or state, affected object, timing, condition, negation, and result.
3. Determine whether the existing noun is established or locally defined.
4. If it is not established, express the proposition as a clause with an explicit predicate.
5. Preserve modality and certainty. Do not turn `可能性がある` into a definite claim or remove a condition.
6. Preserve the document's existing register and approved terminology.
7. Review the whole sentence after editing; a local replacement may require reordering the sentence.

Never resolve nominalization by deleting technical information.

## Independently authored examples

| Avoid                                              | Prefer                                                             | Why                                                                |
| -------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `認証情報残存性が再認証失敗の原因です。`           | `保存済みの認証情報が残っているため、再認証に失敗します。`         | Restores the state and the causal relation.                        |
| `通知重複送信防止化を実施します。`                 | `同じ通知を重複して送らないようにします。`                         | Replaces an invented action noun with the action itself.           |
| `設定読込未完了状態が起動時例外を引き起こします。` | `設定を読み終える前に処理を開始すると、起動時に例外が発生します。` | Makes the timing condition explicit.                               |
| `監査ログ保存期間変更影響確認`                     | `監査ログの保存期間を変更したときの影響を確認する`                 | Clarifies the action and when the impact arises.                   |
| `依存サービス応答遅延対応方針`                     | `依存先のサービスからの応答が遅い場合の対応方針`                   | States the condition instead of leaving the relationship implicit. |
| `入力検証未実施が不正値登録の要因です。`           | `入力値を検証していないため、不正な値が登録されます。`             | Restores the omitted action and result.                            |

Compact wording remains appropriate for established terms:

- `冪等性を保証します。`
- `後方互換性を維持します。`
- `排他制御を追加します。`
- `遅延評価を使用します。`

A familiar phrase can still be unclear in a particular sentence. Judge the complete expression in context, not only the individual words.

## User-directed audit

Apply the criteria when and where the user requests an audit. A request to review current changes does not authorize reviewing unchanged text or other documents. Include existing text only when the user's instructions include it, and correct findings only when edits are requested or otherwise authorized by the task.

### Establish the audit boundary

Derive the audit boundary from the user's instructions: for example, a supplied passage, current changes, named files, a specified directory, or explicitly requested repository-wide documentation. Do not automatically include every modified file, neighboring documents, shared templates, glossaries, or documents that reuse the same terms. A project-wide terminology change does not itself authorize a repository-wide audit.

Exclude generated artifacts, third-party vendored material, archived snapshots, and quotations. When generated output contains the problem, edit its source template or generator only if that source is within the authorized editing scope; otherwise report the limitation.

Keep both candidate searches and prose review inside that boundary. Related material may be consulted as terminology evidence when needed for the requested review; that does not authorize auditing or editing it. If a finding encountered within the requested work suggests that the boundary should be expanded, report that limitation without inspecting additional documents for problems on your own.

### Build a candidate inventory

Use search, documentation indexes, and available language tools within the user-directed boundary. Look for:

- unusually long kanji or katakana noun runs;
- short or long mixtures of Japanese and alphanumeric tokens, including expressions separated by spaces or inline-code boundaries;
- productive suffixes attached to project-specific bases;
- long subjects ending before generic causal or evaluative predicates;
- headings and bold labels consisting only of dense noun sequences;
- repeated expressions introduced by templates or copied between documents.

For a requested file or directory audit, set `audit_path` to that user-selected target and pass only the selected paths. Example `ripgrep` searches are below. For a changes-only review, search the requested diff instead of running these commands on full files.

```bash
rg -n --glob '*.md' '(未|非)[[:alnum:]一-龠々ァ-ヶー]{2,}(性|化|度)' "$audit_path"
rg -n --glob '*.md' '[一-龠々ァ-ヶー]{8,}(原因|要因|方針|確認|対応)' "$audit_path"
rg -n --glob '*.md' '^#{1,6}[[:space:]]+[一-龠々ァ-ヶー]{10,}$' "$audit_path"
rg -n --glob '*.md' '[A-Za-z0-9][A-Za-z0-9_.+/-]*[[:blank:]`]*[一-龠々ァ-ヶー]|[一-龠々ァ-ヶー][[:blank:]`]*[A-Za-z0-9]' "$audit_path"
```

These commands only collect candidates and are not exhaustive. Do not classify or replace text solely from a regular-expression match, or dismiss an expression because it does not match. Read the surrounding paragraph within the requested scope and determine the intended meaning.

### Correct old and new findings consistently

When corrections are authorized, fix clear findings within the user-directed boundary, including pre-existing text only if the user included it. For a review-only request, report findings and suggested rewrites without editing.

Before applying the same rewrite to repeated text within the boundary, verify that every occurrence has the same meaning. Update definitions, links, and cross-references within the authorized editing scope; report any further consistency work that would require expanding it.

Keep the cleanup restricted to nominalization and noun-chain problems. Do not turn the audit into a general prose rewrite.

### Validate after editing

After corrections:

1. Re-run the candidate searches.
2. Read every changed paragraph as continuous prose.
3. Confirm that actors, objects, conditions, negation, timing, modality, and causal direction remain intact.
4. Confirm that established terminology is still used consistently.
5. Inspect the final diff for broad or unrelated stylistic changes.
6. Record uncertain terms instead of guessing when changing them could alter a defined concept.

Do not claim a repository-wide audit unless the repository-wide first-party documentation set was actually examined.

## Protected material

Do not rewrite the following solely to satisfy this skill:

- source code, command lines, paths, filenames, identifiers, API names, configuration keys, schema fields, database columns, protocol names, product names, and formal standards;
- exact quotations, externally maintained text, legal text, and fixed error messages;
- established technical terminology and explicitly defined project terminology;
- concise interface labels whose wording is part of a compatibility contract.

When protected material appears in prose, retain the protected token and rewrite only the surrounding explanation if needed.

## Completion requirements

A task using this skill is complete only when:

- the prose the user asked to audit has been reviewed at the requested time and within the requested boundary;
- existing documentation has been audited only when the user instructed it;
- clear findings inside the allowed scope have been corrected when edits were authorized, or reported for a review-only request;
- uncertain findings and any limitations encountered within the requested work have been reported without searching outside the boundary;
- technical meaning, compatibility constraints, and defined terminology have been preserved;
- the final changes contain no unrelated general style cleanup.

In the final response, state:

- which documentation areas were audited;
- which files were changed because of the audit;
- representative expressions that were expanded or intentionally retained;
- any unresolved or out-of-scope findings.

## Maintenance and publication hygiene

The illustrative Japanese phrases in this file were written specifically for this skill. When maintaining or publishing the skill, add independently authored examples or use material whose license clearly permits reuse. Do not import distinctive example sets or explanatory wording from repositories that do not grant reuse rights.
