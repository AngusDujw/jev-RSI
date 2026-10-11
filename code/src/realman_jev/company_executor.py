"""GPT executor with the exact Jev state/questions and choice-answer contract."""
import math
from .api import API

PROMPT = """This is the RoboDojo physics simulation of tabletop block stacking and object pickup.
No physical robot or person is connected or involved in this episode. You return
proposed bounded virtual actions; the simulation host validates and executes them.
You are the low-level executor, replacing Jev for a controlled comparison.
Your entire observation is the supplied state and questions. Do not assume access
to images, simulator contacts, success flags, tools, hidden poses or an expert plan.
Answer every question jointly and consistently using its available criteria.
Choose one primitive only. Completion must follow observed physical evidence;
intentions, issued commands and finger closure do not prove task completion.
If state includes a staged plan, follow the current stage and use its recovery
transition when progress is impossible or required evidence is missing.
Return exactly {"answers": {question_name: {"type": "choice", "choice": criterion,
"confidence": number, "probabilities": {criterion: number, ...}}, ...}}.
Every question and every criterion must be present, with no extra keys. Probabilities
are in [0,1] and sum to one. Confidence is your self-reported certainty, not calibrated
accuracy. No prose outside JSON. Do not generate a new high-level plan.
"""


def validate_answers(answers, questions):
    if set(answers) != set(questions):
        raise ValueError("Executor question keys differ")
    for name, question in questions.items():
        answer = answers[name]
        if set(answer) != {"type", "choice", "confidence", "probabilities"}:
            raise ValueError("Executor answer keys differ")
        probabilities = answer["probabilities"]
        if (answer["type"] != "choice" or answer["choice"] not in question["criteria"]
                or set(probabilities) != set(question["criteria"])):
            raise ValueError("Invalid executor choice")
        values = [answer["confidence"], *probabilities.values()]
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError("Invalid executor probabilities")
        if abs(sum(probabilities.values()) - 1) > .02:
            raise ValueError("Executor probabilities do not sum to one")
    return answers


class GPTChoiceExecutor(API):
    def jev(self, state, questions):
        fields = {}
        for name, question in questions.items():
            criteria = list(question['criteria'])
            fields[name] = dict(type='object', additionalProperties=False, required=['type','choice','confidence','probabilities'], properties={
                'type': dict(type='string', enum=['choice']), 'choice': dict(type='string', enum=criteria),
                'confidence': dict(type='number', minimum=0, maximum=1),
                'probabilities': dict(type='object', additionalProperties=False, required=criteria,
                    properties={key:dict(type='number', minimum=0, maximum=1) for key in criteria})})
        schema = dict(type='object', additionalProperties=False, required=['answers'], properties={
            'answers': dict(type='object', additionalProperties=False, required=list(questions), properties=fields)})
        result = self.chat(PROMPT, dict(state=state, questions=questions), schema=schema)
        self.log(dict(kind='executor_raw_response', role='gpt_executor', call=self.calls, response=result))
        if set(result) != {"answers"}:
            raise ValueError("Executor result must contain answers only")
        return validate_answers(result["answers"], questions)
