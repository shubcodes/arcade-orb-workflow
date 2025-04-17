#!/usr/bin/env python3
import os
import sys
import asyncio
from arcadepy import Arcade
from arcade.sdk import ToolRegistrar
from arcade.sdk.deployment import deploy_tool

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from custom_tools.gmail_attachment_tool import get_gmail_attachment, list_message_attachments

async def deploy_tools():
    """Deploy the custom Gmail attachment tools to Arcade."""
    print("Deploying custom Gmail attachment tools to Arcade...")
    
    # Get Arcade API key from environment
    api_key = os.getenv("ARCADE_API_KEY")
    if not api_key:
        print("Error: ARCADE_API_KEY environment variable not set")
        return
    
    # Initialize Arcade client
    arcade_client = Arcade(api_key=api_key)
    
    # Register and deploy the tools
    tools = [
        ("Gmail.GetAttachment", get_gmail_attachment),
        ("Gmail.ListAttachments", list_message_attachments)
    ]
    
    for tool_name, tool_function in tools:
        print(f"Deploying {tool_name}...")
        try:
            # Register the tool with Arcade
            registrar = ToolRegistrar()
            registrar.register(tool_function, name=tool_name)
            
            # Deploy the tool
            await deploy_tool(
                registrar=registrar,
                api_key=api_key,
                name=tool_name
            )
            print(f"✅ Successfully deployed {tool_name}")
            
        except Exception as e:
            print(f"❌ Failed to deploy {tool_name}: {str(e)}")
    
    print("Deployment complete!")

if __name__ == "__main__":
    asyncio.run(deploy_tools()) 