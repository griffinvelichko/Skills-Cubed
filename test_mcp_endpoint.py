#!/usr/bin/env python3
"""Quick test of the /mcp endpoint for the Skills-Cubed MCP server."""
import asyncio
import httpx
import json


async def test_mcp_endpoint(base_url="http://localhost:8000"):
    """Test the /mcp endpoint with proper MCP protocol flow."""

    endpoint = f"{base_url}/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        print(f"Testing MCP server at {endpoint}\n")

        # 1. Initialize session
        print("1. Initializing session...")
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"}
            }
        }

        response = await client.post(endpoint, json=init_request, headers=headers)
        print(f"Status: {response.status_code}")

        # Parse SSE response
        lines = response.text.strip().split('\n')
        for line in lines:
            if line.startswith('data: '):
                data = json.loads(line[6:])
                print(f"Session initialized: {data.get('result', {}).get('serverInfo')}\n")

        # Extract session ID from headers
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            headers["mcp-session-id"] = session_id
            print(f"Session ID: {session_id}\n")

        # 2. List tools
        print("2. Listing available tools...")
        list_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }

        response = await client.post(endpoint, json=list_request, headers=headers)
        lines = response.text.strip().split('\n')
        for line in lines:
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if "result" in data:
                    tools = data["result"].get("tools", [])
                    print(f"Found {len(tools)} tools:")
                    for tool in tools:
                        print(f"  - {tool['name']}: {tool.get('description', 'No description')}")

        print("\n3. Testing search_skills tool...")
        search_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_skills",
                "arguments": {
                    "query": "customer cannot log in"
                }
            }
        }

        response = await client.post(endpoint, json=search_request, headers=headers)
        print(f"Status: {response.status_code}")

        lines = response.text.strip().split('\n')
        for line in lines:
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if "result" in data:
                    # tools/call returns content array
                    result = data["result"]
                    if isinstance(result, list) and len(result) > 0:
                        content = result[0].get("content", [])
                        if content and isinstance(content, list):
                            skill_data = content[0].get("text")
                            if skill_data:
                                skill_result = json.loads(skill_data)
                                print(f"Search result:")
                                print(f"  Query: {skill_result.get('query')}")
                                print(f"  Match found: {skill_result.get('skill') is not None}")
                                print(f"  Search time: {skill_result.get('search_time_ms', 0):.2f}ms")
                    else:
                        print(f"Result: {result}")
                elif "error" in data:
                    print(f"Error: {data['error']}")

        print("\n✅ MCP endpoint test complete!")


if __name__ == "__main__":
    asyncio.run(test_mcp_endpoint())
