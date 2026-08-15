//! Session-scoped workflow child-agent budget policy over ACP.
//!
//! `defaultAgentBudget` is used only when a new workflow omits its explicit
//! `agent_budget`. `maxAgentBudget` is a distinct, enforced ceiling for every
//! later launch or resume. Existing active runs retain their admitted budget.

use agent_client_protocol as acp;

use super::{ExtResult, parse_params, to_ext_response};
use crate::agent::MvpAgent;
use crate::session::SessionCommand;

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct WorkflowBudgetRequest {
    session_id: String,
    #[serde(default)]
    default_agent_budget: Option<u64>,
    #[serde(default)]
    max_agent_budget: Option<u64>,
}

/// Read or partially update `x.ai/session/workflow_budget`.
pub async fn handle(agent: &MvpAgent, args: &acp::ExtRequest) -> ExtResult {
    let request: WorkflowBudgetRequest = parse_params(args)?;
    let session_id = acp::SessionId::new(request.session_id.clone());
    let Some(session) = agent.session_handle_waiting_for_load(&session_id).await else {
        return Err(acp::Error::resource_not_found(Some(format!(
            "session not found: {}",
            request.session_id
        ))));
    };

    let (respond_to, response_rx) = tokio::sync::oneshot::channel();
    session
        .cmd_tx
        .send(SessionCommand::ConfigureWorkflowBudget {
            default_agent_budget: request.default_agent_budget,
            max_agent_budget: request.max_agent_budget,
            respond_to,
        })
        .map_err(|_| {
            acp::Error::internal_error().data("resident session command channel is closed")
        })?;
    let policy = response_rx
        .await
        .map_err(|_| {
            acp::Error::internal_error()
                .data("resident session stopped before configuring workflow budget")
        })?
        .map_err(|error| acp::Error::invalid_params().data(error.to_string()))?;

    to_ext_response(Ok(policy))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn partial_request_leaves_unspecified_field_absent() {
        let request: WorkflowBudgetRequest = serde_json::from_value(serde_json::json!({
            "sessionId": "s1",
            "defaultAgentBudget": 64
        }))
        .expect("valid params");
        assert_eq!(request.session_id, "s1");
        assert_eq!(request.default_agent_budget, Some(64));
        assert_eq!(request.max_agent_budget, None);
    }

    #[test]
    fn non_integer_budget_is_rejected() {
        let result = serde_json::from_value::<WorkflowBudgetRequest>(serde_json::json!({
            "sessionId": "s1",
            "maxAgentBudget": "64"
        }));
        assert!(result.is_err());
    }
}
