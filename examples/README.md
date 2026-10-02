# Examples

Every example runs offline (no API keys) against a toy system with planted,
realistic bugs, so you can see what RedSI reports. Run any of them with
`python examples/<name>/run.py`; `python scripts/run_examples.py` runs all.

| # | Example | Shows |
|---|---------|-------|
| 01 | [simple_chatbot](01_simple_chatbot/run.py) | Wrapping a function, built-in suites, capability-based skipping |
| 02 | [rag_system](02_rag_system/run.py) | Reporting `retrieved` documents so findings get a `retrieval_failure` hypothesis |
| 03 | [data_science_assistant](03_data_science_assistant/run.py) | Numeric ground truth, boundary/noise fuzzing |
| 04 | [software_engineering_agent](04_software_engineering_agent/run.py) | Static (non-executing) evaluation of generated code |
| 05 | [tool_using_agent](05_tool_using_agent/run.py) | Tool selection, arguments, side effects, unsafe tool invocation |
| 06 | [aviation_assistant](06_aviation_assistant/run.py) | Synthetic data, spec + ground-truth tests, requirement coverage |
| 07 | [multi_agent_system](07_multi_agent_system/run.py) | Per-agent traces, indirect prompt injection through a pipeline |
| 08 | [specification_driven](08_specification_driven/run.py) | Judge ensemble, disagreement -> `uncertain` |
| 09 | [regression_testing](09_regression_testing/run.py) | Comparing versions, CI gate |
| 10 | [custom_evaluator](10_custom_evaluator/run.py) | Registered evaluator class and wrapped function |
| 11 | [custom_generator](11_custom_generator/run.py) | A new mutation strategy and its failure yield |
| 12 | [custom_target_adapter](12_custom_target_adapter/run.py) | Implementing `TargetAdapter` for a session-based SDK |

To point an example at a real model instead, swap the target, e.g.
`Target.from_openai("gpt-4o-mini")` or `Target.load("ollama:llama3.1")`, and
add judges: `RedSI(target, judges=[provider_from_config("openai:gpt-4o-mini")])`.
