# ruff: noqa
import os
import re
import sys
import json
from datetime import datetime
from typing import Any, AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow, node, FunctionNode, JoinNode, START
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.genai import types

from app.config import config

# -----------------------------------------------------------------------------
# Security Audit Log Helper
# -----------------------------------------------------------------------------
def log_security_decision(severity: str, action: str, details: str):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "severity": severity,
        "action": action,
        "details": details
    }
    log_file = "security_audit.json"
    try:
        data = []
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
        data.append(log_entry)
        with open(log_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error writing security audit log: {e}", file=sys.stderr)

# Helper to extract clean text from inputs
def get_text_from_input(node_input: Any) -> str:
    if isinstance(node_input, str):
        return node_input
    if hasattr(node_input, "parts") and node_input.parts:
        return "".join([p.text for p in node_input.parts if hasattr(p, "text") and p.text])
    if isinstance(node_input, dict):
        return node_input.get("text", str(node_input))
    return str(node_input)

# -----------------------------------------------------------------------------
# MCP Server Toolset Setup
# -----------------------------------------------------------------------------
mcp_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_server.py"))
mcp_tools = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[mcp_path],
        )
    )
)

# -----------------------------------------------------------------------------
# Specialized Sub-Agents
# -----------------------------------------------------------------------------
health_assessor = LlmAgent(
    name="health_assessor",
    model=config.model,
    mode="chat",
    instruction=(
        "You are a Health Assessment Specialist for teenage girls. "
        "Your role is to analyze health concerns (e.g. fatigue, irregular periods, sleep issues) "
        "and suggest potential lifestyle causes or risk factors (like anemia or stress). "
        "Always state clearly when they should seek professional medical advice. "
        "You have access to logging tools to retrieve previous health history for context."
    ),
    description="Analyzes health symptoms, menstrual health, sleep issues, and risks.",
    tools=[mcp_tools],
)

diet_planner = LlmAgent(
    name="diet_planner",
    model=config.model,
    mode="chat",
    instruction=(
        "You are a Diet & Lifestyle Planner for teenage girls. "
        "Your role is to provide nutrition advice, healthy reminders, and customized weekly diet plans. "
        "Check the state for any dietary preferences or allergies (state.get('allergy_info')) "
        "and incorporate them. You have access to tools for logging and retrieving diet entries."
    ),
    description="Provides diet plans, nutrition advice, health reminders, and logs diet history.",
    tools=[mcp_tools],
)

# -----------------------------------------------------------------------------
# Orchestrator Agent
# -----------------------------------------------------------------------------
orchestrator = LlmAgent(
    name="orchestrator",
    model=config.model,
    mode="chat",
    instruction=(
        "You are the Teen Health Assistant Orchestrator. You help teenage girls, parents, and "
        "counselors manage teenage health, diet planning, tracking, and reminders. "
        "For symptom analysis, menstrual concerns, and risk assessment, delegate to the health_assessor agent. "
        "For diet plans, lifestyle improvements, and health reminders, delegate to the diet_planner agent. "
        "Make sure to read any allergy/preference information from the context state. "
        "Synthesize all answers into a friendly, supportive guide. "
        "Always add a medical disclaimer: 'I am an AI assistant, not a doctor. Consult a healthcare professional for medical issues.'"
    ),
    tools=[AgentTool(health_assessor), AgentTool(diet_planner)],
)

# -----------------------------------------------------------------------------
# Workflow Graph Nodes
# -----------------------------------------------------------------------------
def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    text = get_text_from_input(node_input)
    
    # PII Scrubbing
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    phone_pattern = r'\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}'
    
    scrubbed_text = text
    scrubbed_emails = re.findall(email_pattern, text)
    scrubbed_phones = re.findall(phone_pattern, text)
    
    if scrubbed_emails:
        scrubbed_text = re.sub(email_pattern, "[REDACTED_EMAIL]", scrubbed_text)
    if scrubbed_phones:
        scrubbed_text = re.sub(phone_pattern, "[REDACTED_PHONE]", scrubbed_text)
        
    # Prompt Injection Check
    injection_keywords = ["ignore previous instructions", "system prompt", "jailbreak", "dan mode", "you are now"]
    detected_injection = False
    for kw in injection_keywords:
        if kw in text.lower():
            detected_injection = True
            break
            
    if detected_injection:
        log_security_decision("CRITICAL", "PROMPT_INJECTION_DETECTED", f"Input: {text}")
        return Event(output="Security alert: Prompt injection attempt detected. System reset.", route="SECURITY_EVENT")
        
    # Domain-specific safety check (Self-harm / crisis detection)
    self_harm_keywords = ["suicide", "kill myself", "self harm", "end my life", "harm myself"]
    detected_self_harm = False
    for kw in self_harm_keywords:
        if kw in text.lower():
            detected_self_harm = True
            break
            
    if detected_self_harm:
        log_security_decision("CRITICAL", "SELF_HARM_DETECTED", f"Input: {text}")
        return Event(
            output=(
                "Security Warning: If you are experiencing thoughts of self-harm or suicide, "
                "please know that you are not alone and help is available. Please reach out to "
                "a trusted adult, a health professional, or contact the Suicide & Crisis Lifeline "
                "by calling or texting 988 (USA) or your local emergency hotline immediately."
            ),
            route="SECURITY_EVENT"
        )
        
    if scrubbed_emails or scrubbed_phones:
        log_security_decision("WARNING", "PII_REDACTED", f"Redacted emails: {scrubbed_emails}, phones: {scrubbed_phones}")
    else:
        log_security_decision("INFO", "PASS", "No security issues found.")
        
    return Event(output=scrubbed_text, route="normal")

def handle_security_violation(ctx: Context, node_input: Any) -> str:
    return get_text_from_input(node_input)

def route_by_intent(ctx: Context, node_input: Any) -> Event:
    text = get_text_from_input(node_input).lower()
    is_diet_request = any(w in text for w in ["diet", "meal", "food", "eat", "nutrition"])
    
    if is_diet_request and "allergy_info" not in ctx.state:
        return Event(output=node_input, route="need_allergy_info")
    return Event(output=node_input, route="normal")

async def allergy_check(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    if not ctx.resume_inputs or "allergy_query" not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="allergy_query",
            message="Before creating your diet plan, do you have any food allergies or specific dietary preferences (e.g., vegetarian, vegan)? Please let me know so I can tailor it safely."
        )
        return
    
    allergy_info = ctx.resume_inputs["allergy_query"]
    ctx.state["allergy_info"] = allergy_info
    yield Event(output=node_input, state={"allergy_info": allergy_info})

def final_output(ctx: Context, node_input: Any) -> Event:
    text = get_text_from_input(node_input)
    # Yield Content event for the ADK Web UI, and output for downstream
    return Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)]
        ),
        output=text
    )

# -----------------------------------------------------------------------------
# Workflow Definition
# -----------------------------------------------------------------------------
root_agent = Workflow(
    name="teen_health_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"SECURITY_EVENT": handle_security_violation, "normal": route_by_intent}),
        (route_by_intent, {"need_allergy_info": allergy_check, "normal": orchestrator}),
        (allergy_check, orchestrator),
        (orchestrator, final_output),
        (handle_security_violation, final_output)
    ]
)

# App Container setup
app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
