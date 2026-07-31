# AIOS (AI Enterprise Operating System)

AIOS is an enterprise-grade AI platform being built from scratch to understand and implement modern AI systems beyond simply calling LLM APIs.

The objective of this project is to design a modular, production-inspired AI backend capable of powering AI agents, Retrieval-Augmented Generation (RAG), Model Context Protocol (MCP), enterprise workflows, and future multi-agent orchestration.

Instead of relying heavily on frameworks, this project focuses on understanding the engineering decisions behind every component while maintaining a clean, scalable architecture.

---

# Current Version

Version: **1.0**

Status:

- ✅ Backend Foundation
- ✅ Database Layer
- ✅ User Management
- ✅ JWT Authentication
- ✅ OAuth2 Integration

---

# Vision

The long-term goal of AIOS is to build an AI operating system capable of:

- Managing AI Agents
- Running Agent Workflows
- Executing MCP Tools
- Performing Retrieval-Augmented Generation (RAG)
- Integrating Multiple LLM Providers
- Managing Memory
- Supporting Enterprise Authentication
- Monitoring AI Pipelines
- Supporting Human-in-the-Loop workflows

---

# Tech Stack

## Backend

- FastAPI
- SQLAlchemy ORM
- Alembic
- PostgreSQL
- Pydantic v2

## Authentication

- JWT
- OAuth2 Password Flow
- Argon2 Password Hashing
- pwdlib

## Development

- Python 3.12
- Uvicorn
- Swagger UI
- uv Package Manager

---

# Project Structure

backend/

```text
app/
│
├── core/
│   ├── config.py
│   ├── database.py
│   └── security.py
│
├── models/
│   └── user.py
│
├── repositories/
│   └── user_repository.py
│
├── routers/
│   ├── api.py
│   ├── users.py
│   └── v1/
│
├── schemas/
│   └── user.py
│
├── services/
│   └── user_service.py
│
└── main.py

alembic/

pyproject.toml

.env
```

---

# Architecture

The backend follows a layered architecture.

```text
                Client
                   │
                   ▼
             FastAPI Router
                   │
                   ▼
             Service Layer
                   │
                   ▼
           Repository Layer
                   │
                   ▼
             SQLAlchemy ORM
                   │
                   ▼
              PostgreSQL
```

Each layer has a single responsibility.

### Router

Responsible for

- HTTP Requests
- Request Validation
- HTTP Responses

### Service

Responsible for

- Business Logic
- Authentication Logic
- Password Hashing
- Token Generation

### Repository

Responsible for

- Database Operations
- CRUD Queries

### Database

Responsible for

- Persistent Storage

---

# Features Implemented (Version 1)

## Backend Foundation

- FastAPI application setup
- Layered architecture
- Environment configuration using `.env`
- Database connection management
- Dependency Injection
- API Versioning

---

## Database

Implemented using:

- PostgreSQL
- SQLAlchemy ORM
- Alembic

Features:

- Database session management
- Declarative models
- Automatic migrations
- Repository pattern

---

## User Management

Implemented complete CRUD operations.

Features:

- Create User
- Get User
- Get All Users
- Update User
- Delete User

Architecture:

```text
Router
   │
   ▼
Service
   │
   ▼
Repository
   │
   ▼
Database
```

---

## Authentication

Implemented a complete JWT Authentication system.

Features:

- Password Hashing
- Password Verification
- JWT Generation
- JWT Validation
- OAuth2 Password Flow
- Protected Endpoints
- Current User Extraction
- Swagger Authentication

Authentication Flow

```text
User Login
      │
      ▼
Verify Password
      │
      ▼
Generate JWT
      │
      ▼
Client Stores JWT
      │
      ▼
Protected API Request
      │
      ▼
OAuth2PasswordBearer
      │
      ▼
Decode JWT
      │
      ▼
Extract Email
      │
      ▼
Find User
      │
      ▼
Return Current User
```

---

# Password Security

Passwords are never stored in plain text.

Workflow:

```text
Password

↓

Argon2 Hash

↓

Database
```

Example:

```text
$argon2id$v=19$m=65536,t=3,p=4...
```

During login:

```text
Entered Password

↓

Verify Against Hash

↓

Authenticated
```

---

# JWT Authentication

The backend uses JSON Web Tokens (JWT).

Example Payload

```json
{
    "sub": "user@example.com",
    "exp": "expiration_time"
}
```

JWT is used to identify authenticated users without maintaining server-side sessions.

Protected routes automatically extract the authenticated user through FastAPI dependencies.

---

# API Endpoints

## Authentication

| Method | Endpoint | Description |
|---------|----------|-------------|
| POST | `/api/v1/users/login` | Login |

---

## User

| Method | Endpoint |
|---------|----------|
| POST | `/api/v1/users` |
| GET | `/api/v1/users` |
| GET | `/api/v1/users/{id}` |
| GET | `/api/v1/users/me` |
| PUT | `/api/v1/users/{id}` |
| DELETE | `/api/v1/users/{id}` |

---

# Database Schema

## Users Table

| Column | Type |
|----------|------|
| id | Integer |
| email | String |
| hashed_password | String |
| full_name | String |
| is_active | Boolean |
| created_at | DateTime |
| updated_at | DateTime |

---

# Running the Project

## Install dependencies

```bash
uv sync
```

---

## Activate environment

Windows

```bash
.venv\Scripts\activate
```

Linux / macOS

```bash
source .venv/bin/activate
```

---

## Run Backend

```bash
uvicorn app.main:app --reload
```

Swagger

```
http://127.0.0.1:8000/docs
```

---

# Database Migration

Create Migration

```bash
alembic revision --autogenerate -m "message"
```

Apply Migration

```bash
alembic upgrade head
```

Current Version

```bash
alembic current
```

Migration History

```bash
alembic history
```

---

# Environment Variables

Example

```env
DATABASE_URL=postgresql+psycopg://username:password@localhost:5432/aios

SECRET_KEY=your_secret_key

ACCESS_TOKEN_EXPIRE_MINUTES=30
```

---

# Design Philosophy

AIOS is **not** being built as a tutorial project.

The objective is to understand and implement modern AI infrastructure from first principles while following production-inspired software engineering practices.

Every major component is built after understanding:

- Why the technology exists
- What problem it solves
- How it works internally
- How it scales in production
- Trade-offs compared to alternative approaches

The project intentionally prioritizes **understanding over speed**.

---

# Software Architecture Principles

The backend follows several engineering principles.

## Separation of Concerns

Each layer has a single responsibility.

```text
Router
    │
Business Logic
    │
Repository
    │
Database
```

---

## Dependency Injection

FastAPI's dependency injection system is used to manage:

- Database Sessions
- Authentication
- Current User
- Future Services

Example:

```python
db: Session = Depends(get_db)

current_user: User = Depends(get_current_user)
```

---

## Repository Pattern

Database queries remain inside repositories.

Business logic remains inside services.

This makes the code:

- Easier to test
- Easier to maintain
- Easier to extend

---

## API First

The backend is designed independently from the frontend.

Any client can communicate with the API:

- React
- Mobile Applications
- Desktop Applications
- AI Agents
- External Services
- Swagger UI

---

# Current Project Status

## Version 1

### Backend

- [x] FastAPI Setup
- [x] Environment Configuration
- [x] Database Connection
- [x] PostgreSQL
- [x] SQLAlchemy
- [x] Alembic
- [x] CRUD Architecture
- [x] Repository Pattern
- [x] Service Layer

---

### Authentication

- [x] Password Hashing (Argon2)
- [x] Password Verification
- [x] JWT Generation
- [x] JWT Validation
- [x] OAuth2 Password Flow
- [x] Protected Routes
- [x] Current User Dependency
- [x] Swagger Authorization

---

### Testing

- [x] CRUD Endpoints
- [x] Authentication Flow
- [x] JWT Validation
- [x] Protected Routes

---

# Roadmap

## Version 2

Focus:
Production Backend + AI Foundation

Planned Features

- [ ] Global Exception Handling
- [ ] Logging
- [ ] Middleware
- [ ] Request Tracking
- [ ] Configuration Improvements
- [ ] Agent Framework
- [ ] Agent Registry
- [ ] MCP Integration
- [ ] Tool Registry
- [ ] Base AI Agent

---

## Version 3

Focus:
RAG System

Planned Features

- [ ] File Upload
- [ ] Document Processing
- [ ] Text Chunking
- [ ] Embeddings
- [ ] Vector Database
- [ ] Retriever
- [ ] Prompt Builder
- [ ] LLM Integration

---

## Version 4

Focus:
Frontend

Planned Features

- [ ] React
- [ ] Authentication UI
- [ ] Dashboard
- [ ] Agent Management
- [ ] Chat Interface
- [ ] File Upload UI
- [ ] Monitoring Dashboard

---

## Version 5

Focus:
Enterprise

Planned Features

- [ ] Docker
- [ ] Docker Compose
- [ ] Redis
- [ ] Celery
- [ ] Background Tasks
- [ ] Monitoring
- [ ] Metrics
- [ ] CI/CD
- [ ] Deployment

---

# Learning Goals

This project aims to understand:

- Modern Backend Engineering
- Software Architecture
- Authentication
- AI Agents
- RAG
- LLM Integration
- Vector Databases
- MCP
- Production AI Systems
- Enterprise Development Practices

Rather than simply using libraries, the focus is on understanding the engineering principles behind each technology.

---

# Future AIOS Architecture

```text
                     Client
                        │
                        ▼
                FastAPI Backend
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
 Authentication      AI Agents        RAG
        │               │               │
        └───────────────┼───────────────┘
                        ▼
                 LLM Abstraction
                        ▼
                MCP Tool Registry
                        ▼
                  External Tools
                        ▼
                  PostgreSQL
```

---

# Author

**Varun Pant**

Computer Science Engineer

Specialization:
Artificial Intelligence & Data Science

Current Goal:

Design and build production-quality AI systems by understanding every component from first principles rather than relying solely on frameworks.

---

# License

This project is intended for educational, research, and portfolio purposes.

---

**AIOS is an evolving project.**

Each version introduces new capabilities while maintaining clean architecture, scalability, and engineering best practices.