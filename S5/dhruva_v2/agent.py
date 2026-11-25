"""Dhruva v2: an orchestrator that routes each request to one of two specialists."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so adk web can import dhruva_tools

from google.adk.agents import Agent

from dhruva_core import config
from dhruva_tools import escalate_to_analyst, get_application, list_applications, score_application

assessor = Agent(
    name="assessor",
    model=config.MODEL,
    description="Reads and scores startup applications: fit, recommendation, missing evidence, application details, listing.",
    instruction="""You assess startup applications for the Dhruva fund.

- To judge fit, call score_application. Reply with the fit score, the criteria that could not be established,
  and a line written exactly as `Recommendation: <recommendation>` using the tool's recommendation word for word.
- To read a submission, use get_application. To list applications, use list_applications.
- If a tool returns NOT_FOUND, do not retry: say the application was not found.
- Never invent scores or recommendations. Keep replies short.""",
    tools=[list_applications, get_application, score_application],
)

escalation = Agent(
    name="escalation",
    model=config.MODEL,
    description="Hands an application to a human analyst by opening (or re-checking) a ticket.",
    instruction="""You hand startup applications to a human analyst.

- Call escalate_to_analyst with the application id or name and a short reason taken from the request.
- Report the ticket id. If already_open is true, say the ticket was already open and give its id.
- If the tool returns NOT_FOUND, do not retry: say the application was not found.
- Never invent tickets. Keep replies short.""",
    tools=[escalate_to_analyst],
)

root_agent = Agent(
    name="dhruva",
    model=config.MODEL,
    description="Dhruva's triage orchestrator.",
    instruction="""You route requests from Ira, an analyst at the Dhruva fund. Do not answer yourself:
- Questions about an application's fit, a recommendation, its details, or the list of applications: transfer to assessor.
- Requests to escalate, open a ticket, or get a human analyst involved: transfer to escalation.""",
    sub_agents=[assessor, escalation],
)
