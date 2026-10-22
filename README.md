# ennPayables-A2A-RLHF-MCP

## Project Setup and Execution Guide

This repository contains the ennPayables application, including the frontend, backend, AI agents, MCP server, and RLHF tools.

Follow the instructions below to activate the virtual environment and run each component.

## Project Structure

```text
ennPayables/
├── Frontend/
├── Backend/
├── Agent Frontend/
├── mcp_server/
├── Agent/
│   ├── agents/
│   │   ├── agent_1/
│   │   ├── agent_2/
│   │   ├── agent_3/
│   │   └── agent_4/
│   ├── api/
│   └── RLHF_Tools/
└── myenv/
```

## Prerequisites

Make sure the following are installed:

- Python
- Node.js and npm
- Git

Ensure that the Python virtual environment (`myenv`) and the required project dependencies are set up before running the application.

## How to Run the Project

Open separate terminals for the components that need to run simultaneously.

**Note:** All commands below assume you are starting from the repository root directory, `ennPayables`.

### 1. Frontend

Navigate to the `Frontend` directory and start the development server.

```powershell
cd Frontend
npm install
npm run dev -- --host 0.0.0.0
```

### 2. Backend

Navigate to the `Backend` directory, activate the Python virtual environment, and start the backend server.

```powershell
cd Backend
..\myenv\Scripts\activate
python main.py
```

### 3. Agent Frontend

Navigate to the `Agent Frontend` directory and start the development server.

```powershell
cd "Agent Frontend"
npm install
npm run dev -- --host 0.0.0.0
```

### 4. MCP Server

Navigate to the `mcp_server` directory, activate the Python virtual environment, and start the MCP server.

```powershell
cd mcp_server
..\myenv\Scripts\activate
python server.py
```

### 5. Agent 1

Navigate to the `Agent` directory, activate the Python virtual environment, and run Agent 1.

```powershell
cd Agent
..\myenv\Scripts\activate
python -m agents.agent_1.main.main
```

### 6. Agent 2

Run the following command from the `Agent` directory.

```powershell
cd Agent
..\myenv\Scripts\activate
python -m agents.agent_2.main.main
```

### 7. Agent 3

Run the following command from the `Agent` directory.

```powershell
cd Agent
..\myenv\Scripts\activate
python -m agents.agent_3.main.main
```

### 8. Agent 4

Run the following command from the `Agent` directory.

```powershell
cd Agent
..\myenv\Scripts\activate
python -m agents.agent_4.main.main
```

### 9. Agent API

Run the Agent API from the `Agent` directory.

```powershell
cd Agent
..\myenv\Scripts\activate
python -m api.main.main
```

### 10. RLHF Tools API

Navigate to the `RLHF_Tools` directory inside `Agent`, activate the Python virtual environment, and start the RLHF Tools API.

```powershell
cd Agent
cd RLHF_Tools
..\..\myenv\Scripts\activate
python -m api.main
```

## Important Notes

- **Use separate terminals:** Run each component in its own terminal if they need to operate simultaneously.
- **Activate the virtual environment:** For Python components, activate `myenv` before running the Python command.
- **Install frontend dependencies:** Run `npm install` in each frontend directory if dependencies have not been installed.
- **Run commands from the correct directory:** The commands above assume the terminal starts at the repository root. If you are already inside a folder, adjust the `cd` commands accordingly.
- **Environment configuration:** Make sure required environment variables and configuration files are set up before starting the services.
