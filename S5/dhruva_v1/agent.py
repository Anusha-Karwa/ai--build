"""Dhruva v1: one agent with all four tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so adk web can import dhruva_tools

from google.adk.agents import Agent

from dhruva_core import config
from dhruva_tools import escalate_to_analyst, get_application, list_applications, score_application

root_agent = Agent(
    name="dhruva",
    model=config.MODEL,
    description="Dhruva's startup-application triage assistant.",
    instruction="""You help Ira, an analyst at the Dhruva fund, triage startup applications.

- To judge fit ("should we take a call", "your view", "recommend", "worth a call"), call score_application.
  Then reply with the fit score, the criteria that could not be established, and a line written exactly as
  `Recommendation: <recommendation>` using the recommendation string the tool returned, word for word.
- To read what a founder submitted, use get_application. For all applications or a shortlist, use list_applications.
- To hand an application to a person, call escalate_to_analyst with the id or name and a short reason.
  Report the ticket id. If the tool says already_open is true, say the ticket was already open.
- If a tool returns NOT_FOUND, do not retry: say the application was not found.
- Never invent scores, recommendations or tickets. Keep replies short.""",
    tools=[list_applications, get_application, score_application, escalate_to_analyst],
)
