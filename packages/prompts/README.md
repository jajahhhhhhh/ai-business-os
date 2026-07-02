# Prompt templates

Versioned Jinja2 templates, one directory per agent, one file per language:

```
prompts/
└── <agent>/
    ├── <task>.th.j2
    ├── <task>.en.j2
    └── golden/          # golden test cases for the prompt-regression suite (§15)
        └── <task>.jsonl # {input, expected_qualities} pairs scored by the QA agent
```

Rules:
- Prompt changes land as PRs and must pass the regression suite (CI `prompt-regression` job, added in M4).
- Templates receive `context` (assembled memories + KB chunks), `task`, and `locale` — nothing else.
- No prompt strings in agent code; agents load templates by `(agent, task, locale)`.
