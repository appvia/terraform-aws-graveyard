"""
Unit tests for the AWS Organizations account graveyard Lambda handler.

Tests cover:
- OU lookup and retrieval
- Account enumeration
- Account movement with retries
- Lambda handler integration
- Error handling and edge cases
"""

import os
from unittest.mock import MagicMock, call, patch

import pytest

import handler

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_organizations_client():
    """Mock AWS Organizations client."""
    return MagicMock()


@pytest.fixture
def mock_sns_client():
    """Mock AWS SNS client."""
    return MagicMock()


@pytest.fixture
def sample_event():
    """A sample EventBridge event for account closure."""
    return {
        "detail": {
            "requestParameters": {
                "accountId": "123456789012",
            }
        }
    }


@pytest.fixture
def sample_lambda_context():
    """A sample Lambda execution context."""
    context = MagicMock()
    context.request_id = "test-request-id-12345"
    context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:graveyard-handler"
    context.aws_request_id = "test-request-id-12345"
    return context


@pytest.fixture
def sample_ou_tree():
    """Sample organizational unit tree structure."""
    return {
        "root": {
            "Id": "r-abcd",
            "Name": "root",
            "Arn": "arn:aws:organizations::123456789012:root/o-abc123/r-abcd",
        },
        "graveyard": {
            "Id": "ou-graveyard",
            "Name": "Graveyard",
            "Arn": "arn:aws:organizations::123456789012:ou/o-abc123/ou-graveyard",
            "Parent": "r-abcd",
        },
        "engineering": {
            "Id": "ou-engineering",
            "Name": "Engineering",
            "Arn": "arn:aws:organizations::123456789012:ou/o-abc123/ou-engineering",
            "Parent": "r-abcd",
        },
    }


@pytest.fixture
def sample_accounts():
    """Sample AWS accounts with various statuses."""
    return {
        "active": {
            "Id": "111111111111",
            "Name": "production",
            "Arn": "arn:aws:organizations::123456789012:account/o-abc123/111111111111",
            "Status": "ACTIVE",
        },
        "suspended": {
            "Id": "222222222222",
            "Name": "closed-account",
            "Arn": "arn:aws:organizations::123456789012:account/o-abc123/222222222222",
            "Status": "SUSPENDED",
        },
        "another_suspended": {
            "Id": "333333333333",
            "Name": "another-closed",
            "Arn": "arn:aws:organizations::123456789012:account/o-abc123/333333333333",
            "Status": "SUSPENDED",
        },
    }


# ============================================================================
# Tests for get_ou_id_by_name
# ============================================================================


class TestGetOUIdByName:
    """Tests for get_ou_id_by_name function."""

    @patch("handler.organizations_client")
    def test_get_ou_id_by_name_root_level(self, mock_client, sample_ou_tree):
        """Test finding an OU at root level."""
        mock_client.list_roots.return_value = {
            "Roots": [
                {
                    "Id": sample_ou_tree["root"]["Id"],
                    "Name": sample_ou_tree["root"]["Name"],
                }
            ]
        }
        mock_client.get_paginator.return_value.paginate.return_value = [
            {
                "OrganizationalUnits": [
                    {
                        "Id": sample_ou_tree["graveyard"]["Id"],
                        "Name": sample_ou_tree["graveyard"]["Name"],
                    },
                    {
                        "Id": sample_ou_tree["engineering"]["Id"],
                        "Name": sample_ou_tree["engineering"]["Name"],
                    },
                ]
            }
        ]

        ou_id = handler.get_ou_id_by_name("Graveyard")
        assert ou_id == sample_ou_tree["graveyard"]["Id"]

    @patch("handler.organizations_client")
    def test_get_ou_id_by_name_nested(self, mock_client):
        """Test finding a nested OU through recursion."""
        # First call for root OUs
        root_paginator_mock = MagicMock()
        root_paginator_mock.paginate.return_value = [
            {
                "OrganizationalUnits": [
                    {"Id": "ou-parent", "Name": "Parent"},
                ]
            }
        ]

        # Second call for nested OUs
        nested_paginator_mock = MagicMock()
        nested_paginator_mock.paginate.return_value = [
            {
                "OrganizationalUnits": [
                    {"Id": "ou-nested", "Name": "Nested"},
                ]
            }
        ]

        mock_client.list_roots.return_value = {"Roots": [{"Id": "r-root"}]}
        mock_client.get_paginator.side_effect = [
            root_paginator_mock,
            nested_paginator_mock,
        ]

        ou_id = handler.get_ou_id_by_name("Nested")
        assert ou_id == "ou-nested"

    @patch("handler.organizations_client")
    def test_get_ou_id_by_name_not_found(self, mock_client):
        """Test error when OU is not found."""
        mock_client.list_roots.return_value = {"Roots": [{"Id": "r-root"}]}
        
        # Create separate paginators for each call
        root_paginator = MagicMock()
        root_paginator.paginate.return_value = [
            {
                "OrganizationalUnits": [
                    {"Id": "ou-1", "Name": "OUOne"},
                    {"Id": "ou-2", "Name": "OUTwo"},
                ]
            }
        ]
        
        child_paginator = MagicMock()
        child_paginator.paginate.return_value = [{"OrganizationalUnits": []}]
        
        # Return different paginators for root vs child lookups
        mock_client.get_paginator.side_effect = [root_paginator, child_paginator, child_paginator]

        with pytest.raises(ValueError, match="Could not find OU"):
            handler.get_ou_id_by_name("NonExistent")

    @patch("handler.organizations_client")
    def test_get_ou_id_by_name_case_sensitive(self, mock_client):
        """Test OU name matching is case sensitive."""
        mock_client.list_roots.return_value = {"Roots": [{"Id": "r-root"}]}
        
        # First call - exact match case
        first_paginator = MagicMock()
        first_paginator.paginate.return_value = [
            {
                "OrganizationalUnits": [
                    {"Id": "ou-graveyard", "Name": "Graveyard"},
                ]
            }
        ]
        
        # Second call - no match case
        second_root_paginator = MagicMock()
        second_root_paginator.paginate.return_value = [
            {
                "OrganizationalUnits": [
                    {"Id": "ou-graveyard", "Name": "Graveyard"},
                ]
            }
        ]
        
        child_paginator = MagicMock()
        child_paginator.paginate.return_value = [{"OrganizationalUnits": []}]
        
        mock_client.get_paginator.side_effect = [
            first_paginator,
            second_root_paginator,
            child_paginator
        ]

        # Exact case should match
        ou_id = handler.get_ou_id_by_name("Graveyard")
        assert ou_id == "ou-graveyard"

        # Different case should not match
        with pytest.raises(ValueError, match="Could not find OU"):
            handler.get_ou_id_by_name("graveyard")


# ============================================================================
# Tests for get_current_parent
# ============================================================================


class TestGetCurrentParent:
    """Tests for get_current_parent function."""

    @patch("handler.organizations_client")
    def test_get_current_parent_success(self, mock_client):
        """Test retrieving parent OU for an account."""
        account_id = "123456789012"
        parent_id = "ou-parent-id"

        mock_client.list_parents.return_value = {
            "Parents": [
                {
                    "Id": parent_id,
                    "Type": "ORGANIZATIONAL_UNIT",
                }
            ]
        }

        result = handler.get_current_parent(account_id)
        assert result == parent_id
        mock_client.list_parents.assert_called_once_with(ChildId=account_id)

    @patch("handler.organizations_client")
    def test_get_current_parent_not_found(self, mock_client):
        """Test error when account parent is not found."""
        account_id = "123456789012"

        mock_client.list_parents.return_value = {"Parents": []}

        with pytest.raises(ValueError, match="Could not find parent"):
            handler.get_current_parent(account_id)

    @patch("handler.organizations_client")
    def test_get_current_parent_root(self, mock_client):
        """Test retrieving parent when account is under root."""
        account_id = "123456789012"
        root_id = "r-abcd"

        mock_client.list_parents.return_value = {
            "Parents": [
                {
                    "Id": root_id,
                    "Type": "ROOT",
                }
            ]
        }

        result = handler.get_current_parent(account_id)
        assert result == root_id


# ============================================================================
# Tests for get_accounts_to_process
# ============================================================================


class TestGetAccountsToProcess:
    """Tests for get_accounts_to_process function."""

    @patch("handler.organizations_client")
    @patch("handler.get_current_parent")
    def test_get_accounts_to_process_finds_closed_accounts(
        self, mock_get_parent, mock_client, sample_accounts
    ):
        """Test finding suspended accounts not in graveyard."""
        graveyard_ou_id = "ou-graveyard"

        # Mock get_paginator
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {
                "Accounts": [
                    sample_accounts["active"],
                    sample_accounts["suspended"],
                    sample_accounts["another_suspended"],
                ]
            }
        ]
        mock_client.get_paginator.return_value = paginator_mock

        # Setup parent lookup
        def parent_side_effect(account_id):
            if account_id == "111111111111":
                return "ou-engineering"
            return "ou-other"

        mock_get_parent.side_effect = parent_side_effect

        accounts = handler.get_accounts_to_process(graveyard_ou_id)

        # Should return both suspended accounts
        assert len(accounts) == 2
        assert "222222222222" in accounts
        assert "333333333333" in accounts

    @patch("handler.organizations_client")
    @patch("handler.get_current_parent")
    def test_get_accounts_to_process_excludes_active(
        self, mock_get_parent, mock_client, sample_accounts
    ):
        """Test that active accounts are not included."""
        graveyard_ou_id = "ou-graveyard"

        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {"Accounts": [sample_accounts["active"]]}
        ]
        mock_client.get_paginator.return_value = paginator_mock

        accounts = handler.get_accounts_to_process(graveyard_ou_id)

        assert len(accounts) == 0

    @patch("handler.organizations_client")
    @patch("handler.get_current_parent")
    def test_get_accounts_to_process_excludes_already_in_graveyard(
        self, mock_get_parent, mock_client, sample_accounts
    ):
        """Test that suspended accounts already in graveyard are excluded."""
        graveyard_ou_id = "ou-graveyard"

        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {
                "Accounts": [
                    sample_accounts["suspended"],
                    sample_accounts["another_suspended"],
                ]
            }
        ]
        mock_client.get_paginator.return_value = paginator_mock

        # First account is in graveyard, second is not
        def parent_side_effect(account_id):
            if account_id == "222222222222":
                return graveyard_ou_id
            return "ou-other"

        mock_get_parent.side_effect = parent_side_effect

        accounts = handler.get_accounts_to_process(graveyard_ou_id)

        # Should only return the one not in graveyard
        assert len(accounts) == 1
        assert accounts[0] == "333333333333"

    @patch("handler.organizations_client")
    def test_get_accounts_to_process_no_closed_accounts(self, mock_client):
        """Test when there are no closed accounts to process."""
        graveyard_ou_id = "ou-graveyard"

        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {
                "Accounts": [
                    {
                        "Id": "111111111111",
                        "Status": "ACTIVE",
                    },
                    {
                        "Id": "222222222222",
                        "Status": "ACTIVE",
                    },
                ]
            }
        ]
        mock_client.get_paginator.return_value = paginator_mock

        accounts = handler.get_accounts_to_process(graveyard_ou_id)

        assert len(accounts) == 0

    @patch("handler.organizations_client")
    def test_get_accounts_to_process_pagination(self, mock_client):
        """Test handling multiple pages of accounts."""
        graveyard_ou_id = "ou-graveyard"

        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {
                "Accounts": [
                    {"Id": "111111111111", "Status": "ACTIVE", "Name": "acc1"},
                ]
            },
            {
                "Accounts": [
                    {"Id": "222222222222", "Status": "SUSPENDED", "Name": "acc2"},
                ]
            },
        ]
        mock_client.get_paginator.return_value = paginator_mock

        with patch("handler.get_current_parent", return_value="ou-other"):
            accounts = handler.get_accounts_to_process(graveyard_ou_id)

        # Should find the suspended account in second page
        assert len(accounts) == 1
        assert accounts[0] == "222222222222"

    @patch("handler.organizations_client")
    def test_get_accounts_to_process_handles_error(self, mock_client):
        """Test error handling when listing accounts fails."""
        graveyard_ou_id = "ou-graveyard"

        paginator_mock = MagicMock()
        paginator_mock.paginate.side_effect = Exception("API Error")
        mock_client.get_paginator.return_value = paginator_mock

        with pytest.raises(Exception, match="API Error"):
            handler.get_accounts_to_process(graveyard_ou_id)


# ============================================================================
# Tests for move account logic
# ============================================================================


class TestMoveAccount:
    """Tests for account movement with retries."""

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    def test_move_account_success_first_attempt(
        self,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test successful account move on first attempt."""
        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"
        source_parent = "ou-engineering"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = source_parent
        mock_client.move_account.return_value = {}

        event = {}
        result = handler.lambda_handler(event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert result["body"]["total_processed"] == 1
        assert account_id in result["body"]["processed_accounts"]
        mock_client.move_account.assert_called_once_with(
            AccountId=account_id,
            SourceParentId=source_parent,
            DestinationParentId=graveyard_ou,
        )

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    @patch("handler.time")
    def test_move_account_retry_on_failure(
        self,
        mock_time,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test account move retries on ClientError then succeeds."""
        from botocore.exceptions import ClientError

        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"
        source_parent = "ou-engineering"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = source_parent

        # First call fails, second succeeds
        error_response = {"Error": {"Code": "ServiceUnavailableException"}}
        mock_client.move_account.side_effect = [
            ClientError(error_response, "MoveAccount"),
            {},
        ]

        event = {}
        result = handler.lambda_handler(event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert result["body"]["total_processed"] == 1
        assert account_id in result["body"]["processed_accounts"]
        # Should have called move_account twice (initial + retry)
        assert mock_client.move_account.call_count == 2

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    @patch("handler.time")
    def test_move_account_exhausts_retries(
        self,
        mock_time,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test account move fails after exhausting retries."""
        from botocore.exceptions import ClientError

        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"
        source_parent = "ou-engineering"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = source_parent

        # All attempts fail
        error_response = {"Error": {"Code": "ServiceUnavailableException"}}
        mock_client.move_account.side_effect = ClientError(
            error_response, "MoveAccount"
        )

        event = {}
        result = handler.lambda_handler(event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert result["body"]["total_failed"] == 1
        assert account_id in result["body"]["failed_accounts"]
        # Should have called move_account 3 times (max retries)
        assert mock_client.move_account.call_count == 3

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    def test_move_account_exponential_backoff(
        self,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test exponential backoff retry delays."""
        from botocore.exceptions import ClientError

        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"
        source_parent = "ou-engineering"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = source_parent

        error_response = {"Error": {"Code": "ServiceUnavailableException"}}
        mock_client.move_account.side_effect = ClientError(
            error_response, "MoveAccount"
        )

        with patch("handler.time.sleep") as mock_sleep:
            handler.lambda_handler({}, sample_lambda_context)

            # Should have delays of 1, 2 seconds (2^0 * 1, 2^1 * 1)
            sleep_calls = mock_sleep.call_args_list
            assert len(sleep_calls) == 2
            assert sleep_calls[0] == call(1)  # First retry: 1 second
            assert sleep_calls[1] == call(2)  # Second retry: 2 seconds


# ============================================================================
# Tests for lambda_handler
# ============================================================================


class TestLambdaHandler:
    """Tests for the main lambda_handler function."""

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    def test_lambda_handler_no_accounts_to_process(
        self,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test handler when no closed accounts need processing."""
        graveyard_ou = "ou-graveyard"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = []

        event = {}
        result = handler.lambda_handler(event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert "No closed accounts found to process" in result["body"]

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    def test_lambda_handler_multiple_accounts(
        self,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test handler processes multiple closed accounts."""
        graveyard_ou = "ou-graveyard"
        accounts = ["111111111111", "222222222222", "333333333333"]

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = accounts
        mock_get_parent.return_value = "ou-other"
        mock_client.move_account.return_value = {}

        event = {}
        result = handler.lambda_handler(event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert result["body"]["total_processed"] == 3
        assert len(result["body"]["processed_accounts"]) == 3
        assert mock_client.move_account.call_count == 3

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    def test_lambda_handler_mixed_success_and_failure(
        self,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test handler with mixed success and failure outcomes."""
        from botocore.exceptions import ClientError

        graveyard_ou = "ou-graveyard"
        accounts = ["111111111111", "222222222222"]

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = accounts
        mock_get_parent.return_value = "ou-other"

        # First succeeds, second fails
        error_response = {"Error": {"Code": "AccessDeniedException"}}
        mock_client.move_account.side_effect = [
            {},
            ClientError(error_response, "MoveAccount"),
            ClientError(error_response, "MoveAccount"),
            ClientError(error_response, "MoveAccount"),
        ]

        with patch("handler.time.sleep"):
            event = {}
            result = handler.lambda_handler(event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert result["body"]["total_processed"] == 1
        assert result["body"]["total_failed"] == 1
        assert accounts[0] in result["body"]["processed_accounts"]
        assert accounts[1] in result["body"]["failed_accounts"]

    @patch.dict(
        os.environ,
        {},
        clear=True,
    )
    def test_lambda_handler_missing_environment_variable(self, sample_lambda_context):
        """Test handler fails when GRAVEYARD_OU_NAME is not set."""
        event = {}

        with pytest.raises(KeyError):
            handler.lambda_handler(event, sample_lambda_context)

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.get_ou_id_by_name")
    def test_lambda_handler_graveyard_ou_not_found(
        self, mock_get_ou, sample_lambda_context
    ):
        """Test handler fails when graveyard OU doesn't exist."""
        mock_get_ou.side_effect = ValueError("Could not find OU with name: Graveyard")

        event = {}

        with pytest.raises(ValueError, match="Could not find OU"):
            handler.lambda_handler(event, sample_lambda_context)

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    def test_lambda_handler_accounts_listing_error(
        self,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test handler propagates error from account listing."""
        graveyard_ou = "ou-graveyard"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.side_effect = Exception("Organizations API error")

        event = {}

        with pytest.raises(Exception, match="Organizations API error"):
            handler.lambda_handler(event, sample_lambda_context)

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    def test_lambda_handler_returns_structured_response(
        self,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test handler returns well-structured response."""
        graveyard_ou = "ou-graveyard"
        accounts = ["111111111111", "222222222222"]

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = accounts
        mock_get_parent.return_value = "ou-other"
        mock_client.move_account.return_value = {}

        event = {}
        result = handler.lambda_handler(event, sample_lambda_context)

        # Validate response structure
        assert "statusCode" in result
        assert result["statusCode"] == 200
        assert "body" in result
        assert "processed_accounts" in result["body"]
        assert "failed_accounts" in result["body"]
        assert "total_processed" in result["body"]
        assert "total_failed" in result["body"]
        assert isinstance(result["body"]["processed_accounts"], list)
        assert isinstance(result["body"]["failed_accounts"], list)

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    def test_lambda_handler_with_event_payload(
        self,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
        sample_event,
    ):
        """Test handler processes event payload correctly."""
        graveyard_ou = "ou-graveyard"
        accounts = ["222222222222"]

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = accounts
        mock_get_parent.return_value = "ou-engineering"
        mock_client.move_account.return_value = {}

        result = handler.lambda_handler(sample_event, sample_lambda_context)

        assert result["statusCode"] == 200
        assert result["body"]["total_processed"] == 1


# ============================================================================
# Tests for logging
# ============================================================================


class TestLogging:
    """Tests for JSON structured logging."""

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard", "LOG_LEVEL": "DEBUG"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    @patch("handler.logger")
    def test_logging_on_account_found(
        self,
        mock_logger,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test logging when closed account is found."""
        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = "ou-engineering"
        mock_client.move_account.return_value = {}

        event = {}
        handler.lambda_handler(event, sample_lambda_context)

        # Verify logging was called
        assert mock_logger.info.called

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    @patch("handler.logger")
    def test_logging_on_move_success(
        self,
        mock_logger,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test logging when account move succeeds."""
        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = "ou-engineering"
        mock_client.move_account.return_value = {}

        event = {}
        handler.lambda_handler(event, sample_lambda_context)

        # Verify success was logged
        mock_logger.info.assert_called()

    @patch.dict(
        os.environ,
        {"GRAVEYARD_OU_NAME": "Graveyard"},
    )
    @patch("handler.organizations_client")
    @patch("handler.get_ou_id_by_name")
    @patch("handler.get_accounts_to_process")
    @patch("handler.get_current_parent")
    @patch("handler.logger")
    def test_logging_on_move_error(
        self,
        mock_logger,
        mock_get_parent,
        mock_get_accounts,
        mock_get_ou,
        mock_client,
        sample_lambda_context,
    ):
        """Test logging when account move fails."""
        from botocore.exceptions import ClientError

        graveyard_ou = "ou-graveyard"
        account_id = "222222222222"

        mock_get_ou.return_value = graveyard_ou
        mock_get_accounts.return_value = [account_id]
        mock_get_parent.return_value = "ou-engineering"

        error_response = {"Error": {"Code": "AccessDeniedException"}}
        mock_client.move_account.side_effect = ClientError(
            error_response, "MoveAccount"
        )

        with patch("handler.time.sleep"):
            event = {}
            handler.lambda_handler(event, sample_lambda_context)

        # Verify error was logged
        mock_logger.error.assert_called()
