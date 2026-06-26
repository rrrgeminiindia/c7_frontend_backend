import os
import gradio as gr
import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000/diagnose")


def diagnose(message, history):
    try:
        response = requests.post(
            BACKEND_URL,
            json={"workflow_description": message},
            timeout=60,
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        return f"Could not reach the backend.\n\n{e}"


demo = gr.ChatInterface(
    diagnose,
    title="Workflow Diagnoser",
    description="Describe one repeated task you do at work.",
)

if __name__ == "__main__":
    demo.launch()
