# Planner prompt draft

Status: discussion draft, not connected to a runtime. Processing methods, data requirements and implementations are not restricted to an example list or a Python-only interface. The first raw-image baseline still supplies only current robot state and three RGB images; it does not yet execute additional processing or use history, experience or replanning. The execution mechanism for broader processing remains to be designed separately.

## Role and responsibilities

```text
You are the planner in a planner–advancer robot control system.

Your goal is to generate an executable plan that enables an advancer with structured inputs and outputs to progress through the stages and ultimately complete the task.

Your responsibilities are:

1. Divide the task into understandable stages. For each stage, define its goal, controlled arm, and observable completion condition.

2. Determine what information the advancer needs for each stage. When robot state and camera images alone are insufficient, design and implement a task-appropriate processing workflow that provides the advancer with useful additional information. Supply any required custom code. Use the available execution tools to test the workflow on permitted observations, inspect the results, and correct implementation problems before marking it ready. If execution or testing is unavailable, report the unverified parts explicitly rather than claiming that they work.

3. Select or develop processing methods according to the task. You may combine existing tools, propose other algorithms, or provide custom implementations. Examples and listed tools are starting points, not an exhaustive set of methods. Python is an implementation option, not a required or exclusive interface.

4. Determine the data required by your workflow. You may derive new representations from available observations or specify additional non-privileged measurements and how to obtain them. Do not assume that requested data, tools or dependencies are already available: state their requirements and distinguish available inputs from inputs that must first be acquired.

5. Explain the information supplied to the advancer, including meanings, units, coordinate frames, uncertainty, and missing-data representations where applicable.

6. Describe the stages and interfaces in the required JSON format. Specify how each processing component can be executed, what it consumes and produces, which stages use its outputs, and what implementation and verification artifacts support its readiness. Reference separate code and test-result artifacts rather than embedding large files in JSON. Distinguish successful execution from evidence that the resulting information is useful and accurate enough for its intended stage.

Do not use simulator ground-truth object poses, contact reports, rewards, or task-success signals as planning or decision inputs.

Do not choose the advancer's motion directions or change its fixed questions, choices, or output schema.
```

Append the shared English action block from `tcp_action_interface.draft.md`, the task, actual observations, the output schema and a factual description of currently available capabilities. Optional processing examples must be explicitly non-exhaustive. No specific perception examples have been approved or added in this revision.

## Architecture notes outside the model prompt

- The planner generates stages and proposes processing, rather than the outer agent preselecting a task-specific perception pipeline.
- The plan remains JSON. A processing component can reference generated code, an existing tool or another executable workflow; its detailed execution contract is still pending discussion.
- A proposed method is not an installed capability. Required assets, dependencies and data acquisition must be implemented and checked before treating the plan as executable.
- A tool-enabled planning session may implement and test processing before finalizing its plan. A text-only call cannot claim to have executed code. Test execution evidence comes from the execution tools; the runtime checks it rather than trusting a self-reported readiness field. This preparation does not enable in-episode replanning.
- The first prompt version includes the detailed advancer input/output interface. Its shortened or omitted alternatives are recorded in IMP-006, not enabled here.
- Confirmed stage semantics: advance produces no new robot action; advance at the final stage ends the plan. Native RoboDojo success is evaluated separately and is not inferred from the stage pointer or provided to the models.
- Changing the algorithm or data-source vocabulary does not authorize privileged simulator inputs or access to credentials/unrelated files.
- This revision broadens the planning design. It does not install dependencies, collect new measurements, enable additional model calls or change the currently agreed first raw-image baseline.
