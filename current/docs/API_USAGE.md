# Energy Cost Calculator API Usage Guide

## Overview

## API Server Setup

1. Install dependencies:
```bash
pip install fastapi uvicorn sqlalchemy pydantic requests
```

2. Start the API server:
```bash
uvicorn api.main:app --reload
```

The API will be available at `http://localhost:8000`


## Common Issues

1. **API Connection Failed**
   - Check if the API server is running
   - Verify the API URL is correct
   - Check network connectivity

2. **Invalid Customer ID**
   - Ensure the customer exists in the database
   - Verify the customer has associated meter readings

3. **No Data for Period**
   - Check if meter readings exist for the specified date range
   - Verify the date format is correct (YYYY-MM-DD)
