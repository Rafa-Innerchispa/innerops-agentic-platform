# Lógica CrewAI para catalyst_rag_bridge (AG-09)
from crewai import Agent, Task, Crew
import yaml
import os

def run(context_variables):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    with open(os.path.join(base_dir, "config", "agent.yaml"), "r") as f:
        agent_config = yaml.safe_load(f)["catalyst_rag_bridge"]
        
    with open(os.path.join(base_dir, "config", "tasks.yaml"), "r") as f:
        task_config = yaml.safe_load(f)["query_rag"]

    # Instanciación nativa de CrewAI
    agent_inst = Agent(
        role=agent_config["role"],
        goal=agent_config["goal"],
        backstory=agent_config["backstory"],
        verbose=True,
        memory=False
    )
    
    task_inst = Task(
        description=task_config["description"].format(**context_variables),
        expected_output=task_config["expected_output"],
        agent=agent_inst
    )
    
    crew = Crew(
        agents=[agent_inst],
        tasks=[task_inst],
        verbose=True
    )
    
    return crew.kickoff(inputs=context_variables)
