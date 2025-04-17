import pytest
import respx
import json
from httpx import Response

# Updated import path
from arcade_orb_toolkit.tools.orb_api import (
    create_customer,
    get_customer,
    create_subscription,
    get_subscription,
    ORB_API_URL # Import the base URL used in the tools
)

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio

# --- Test Data ---
MOCK_CUSTOMER_ID = "cust_test123"
MOCK_SUBSCRIPTION_ID = "sub_test456"
MOCK_PLAN_ID = "plan_pro_monthly"

CUSTOMER_PAYLOAD = {
    "name": "Test Customer",
    "email": "test@example.com",
    "address": {
        "street": "123 Test St",
        "city": "Testville",
        "state": "TS",
        "zip_code": "12345",
        "country": "TC"
    }
}

CUSTOMER_RESPONSE = {
    "id": MOCK_CUSTOMER_ID,
    "name": "Test Customer",
    "email": "test@example.com",
    "address": {
        "street": "123 Test St",
        "city": "Testville",
        "state": "TS",
        "zip_code": "12345",
        "country": "TC"
    },
    "created_at": "2024-01-01T10:00:00Z"
}

SUBSCRIPTION_PAYLOAD = {
    "customer_id": MOCK_CUSTOMER_ID,
    "plan_id": MOCK_PLAN_ID,
    "user_count": 5,
    "addons": ["addon_abc"]
}

SUBSCRIPTION_RESPONSE = {
    **SUBSCRIPTION_PAYLOAD,
    "id": MOCK_SUBSCRIPTION_ID,
    "status": "active",
    "created_at": "2024-01-01T11:00:00Z"
}

NOT_FOUND_RESPONSE = {"error": "Not Found", "details": "Resource not found"}
API_ERROR_RESPONSE = {"error": "Internal Server Error", "details": "Something went wrong"}


# --- Test Cases ---
@respx.mock
async def test_create_customer_success():
    """Test successful customer creation."""
    # Mock the POST request
    route = respx.post(f"{ORB_API_URL}/customers").mock(return_value=Response(201, json=CUSTOMER_RESPONSE))

    # Call the tool
    result = await create_customer(
        name=CUSTOMER_PAYLOAD["name"],
        email=CUSTOMER_PAYLOAD["email"],
        address_street=CUSTOMER_PAYLOAD["address"]["street"],
        address_city=CUSTOMER_PAYLOAD["address"]["city"],
        address_state=CUSTOMER_PAYLOAD["address"]["state"],
        address_zip_code=CUSTOMER_PAYLOAD["address"]["zip_code"],
        address_country=CUSTOMER_PAYLOAD["address"]["country"]
    )

    # Assertions
    assert route.called
    sent_payload = json.loads(route.calls.last.request.content)
    assert sent_payload == CUSTOMER_PAYLOAD # Check payload sent matches input
    assert result == CUSTOMER_RESPONSE

@respx.mock
async def test_create_customer_no_address():
    """Test successful customer creation without address details."""
    expected_payload = {"name": "No Address Cust", "email": "noaddress@test.com"}
    mock_response = {**expected_payload, "id": "cust_noaddr", "created_at": "2024-01-02T00:00:00Z"}
    route = respx.post(f"{ORB_API_URL}/customers").mock(return_value=Response(201, json=mock_response))

    result = await create_customer(name="No Address Cust", email="noaddress@test.com")

    assert route.called
    sent_payload = json.loads(route.calls.last.request.content)
    assert sent_payload == expected_payload # Address should not be included
    assert result == mock_response

@respx.mock
async def test_create_customer_api_error():
    """Test customer creation with API error (e.g., 500)."""
    route = respx.post(f"{ORB_API_URL}/customers").mock(return_value=Response(500, json=API_ERROR_RESPONSE))

    result = await create_customer(name="Error Case", email="error@example.com")

    assert route.called
    assert result.get("error") == "API Error: 500"
    # Check details (which should be the parsed JSON body from the error response)
    assert result.get("details") == API_ERROR_RESPONSE

@respx.mock
async def test_get_customer_success():
    """Test successfully retrieving a customer."""
    route = respx.get(f"{ORB_API_URL}/customers/{MOCK_CUSTOMER_ID}").mock(return_value=Response(200, json=CUSTOMER_RESPONSE))

    result = await get_customer(customer_id=MOCK_CUSTOMER_ID)

    assert route.called
    assert result == CUSTOMER_RESPONSE

@respx.mock
async def test_get_customer_not_found():
    """Test retrieving a non-existent customer."""
    route = respx.get(f"{ORB_API_URL}/customers/invalid_id").mock(return_value=Response(404, json=NOT_FOUND_RESPONSE))

    result = await get_customer(customer_id="invalid_id")

    assert route.called
    assert result.get("error") == "API Error: 404"
    assert result.get("details") == NOT_FOUND_RESPONSE

@respx.mock
async def test_create_subscription_success():
    """Test successful subscription creation."""
    route = respx.post(f"{ORB_API_URL}/subscriptions").mock(return_value=Response(201, json=SUBSCRIPTION_RESPONSE))

    result = await create_subscription(
        customer_id=SUBSCRIPTION_PAYLOAD["customer_id"],
        plan_id=SUBSCRIPTION_PAYLOAD["plan_id"],
        user_count=SUBSCRIPTION_PAYLOAD["user_count"],
        addons=SUBSCRIPTION_PAYLOAD["addons"]
    )

    assert route.called
    sent_payload = json.loads(route.calls.last.request.content)
    assert sent_payload == SUBSCRIPTION_PAYLOAD
    assert result == SUBSCRIPTION_RESPONSE

@respx.mock
async def test_create_subscription_api_error():
    """Test subscription creation with API error."""
    mock_error_body = {"error": "Bad Request", "details": "Missing required field"}
    route = respx.post(f"{ORB_API_URL}/subscriptions").mock(return_value=Response(400, json=mock_error_body))

    result = await create_subscription(customer_id=MOCK_CUSTOMER_ID, plan_id="invalid_plan")

    assert route.called
    assert result.get("error") == "API Error: 400"
    assert result.get("details") == mock_error_body

@respx.mock
async def test_get_subscription_success():
    """Test successfully retrieving a subscription."""
    route = respx.get(f"{ORB_API_URL}/subscriptions/{MOCK_SUBSCRIPTION_ID}").mock(return_value=Response(200, json=SUBSCRIPTION_RESPONSE))

    result = await get_subscription(subscription_id=MOCK_SUBSCRIPTION_ID)

    assert route.called
    assert result == SUBSCRIPTION_RESPONSE

@respx.mock
async def test_get_subscription_not_found():
    """Test retrieving a non-existent subscription."""
    route = respx.get(f"{ORB_API_URL}/subscriptions/invalid_sub_id").mock(return_value=Response(404, json=NOT_FOUND_RESPONSE))

    result = await get_subscription(subscription_id="invalid_sub_id")

    assert route.called
    assert result.get("error") == "API Error: 404"
    assert result.get("details") == NOT_FOUND_RESPONSE 