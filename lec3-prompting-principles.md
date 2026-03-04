# Prompting Principles (from lec3-prompting-3)

This note distills the prompt engineering techniques requested by the user from:

- `/Users/yukun/Downloads/lec3-prompting-3 (1).pdf`

## Core Idea

Compose prompts from explicit elements instead of ad-hoc prose.

## Ten Prompt Elements

1. **User role framing**
   - Message starts from user intent and interaction context.
2. **Task context**
   - Define role, mission, and goal clearly.
3. **Tone context**
   - Specify tone only when it affects output quality.
4. **Detailed task description and rules**
   - Include hard constraints and "must not" boundaries.
5. **Examples (few-shot)**
   - Most effective lever for quality in complex tasks.
   - Include edge cases and failure examples.
6. **Input data block**
   - Delimit input sections (`<input>...</input>` style) to reduce confusion.
7. **Immediate task restatement**
   - End with the exact action for this turn.
8. **Process guidance**
   - Ask for stepwise reasoning process internally.
   - Do not require exposing chain-of-thought in final output.
9. **Output formatting**
   - Define rigid output schema, field constraints, and ordering.
10. **Optional response prefill**
   - Useful when style/shape must be forced (context dependent).

## Practical Guidance

1. Start with a modular prompt skeleton.
2. Add examples early for brittle tasks.
3. Cover common edge cases explicitly.
4. Prefer clear constraints over vague style requests.
5. Keep prompt concise once behavior stabilizes.

## Anti-Patterns

1. Overly broad instructions without constraints.
2. Schema ambiguity (`maybe`, `if needed`) without rules.
3. Missing refusal behavior when evidence is weak.
4. Missing failure-mode examples.

