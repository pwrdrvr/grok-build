use agent_client_protocol::{self as acp};

use crate::agent::handlers::model_switch::{self, ConfigNotice};
use crate::agent::mvp_agent::MvpAgent;
use crate::agent::session_config::{
    CONFIG_ID_MODEL, CONFIG_ID_PERMISSION_MODE, CONFIG_ID_REASONING_EFFORT,
};

pub(crate) async fn apply(
    agent: &MvpAgent,
    args: acp::SetSessionConfigOptionRequest,
) -> Result<acp::SetSessionConfigOptionResponse, acp::Error> {
    let acp::SetSessionConfigOptionRequest {
        session_id,
        config_id,
        value,
        ..
    } = args;

    match config_id.0.as_ref() {
        CONFIG_ID_PERMISSION_MODE => {
            let value_id = value.as_value_id().ok_or_else(|| {
                acp::Error::invalid_params().data("permission_mode requires a string value")
            })?;
            let handle = agent.resident_handle(&session_id).ok_or_else(|| {
                acp::Error::invalid_params().data("session is not resident")
            })?;
            let cmd_tx = handle.cmd_tx.clone();
            drop(handle);
            let (tx, rx) = tokio::sync::oneshot::channel();
            cmd_tx
                .send(crate::session::SessionCommand::SetPermissionMode {
                    mode: value_id.0.to_string(),
                    respond_to: tx,
                })
                .map_err(|_| acp::Error::internal_error().data("session command channel closed"))?;
            rx.await
                .map_err(|_| acp::Error::internal_error().data("session did not acknowledge permission mode"))?
                .map_err(|reason| acp::Error::invalid_params().data(reason))?;
            agent.with_resident_mut(&session_id, |handle| {
                handle.yolo_mode = handle.permission_handle.is_yolo_mode();
            });
        }
        CONFIG_ID_MODEL => {
            let value_id = value.as_value_id().ok_or_else(|| {
                acp::Error::invalid_params().data("model requires a string value")
            })?;
            let request = acp::SetSessionModelRequest::new(
                session_id.clone(),
                acp::ModelId::new(value_id.0.clone()),
            );
            agent.set_model_gated(request).await?;
        }
        CONFIG_ID_REASONING_EFFORT => {
            let value_id = value.as_value_id().ok_or_else(|| {
                acp::Error::invalid_params().data("reasoning_effort requires a string value")
            })?;
            // The selector is resolved inside `apply_reasoning_effort` under the config lock, so
            // it is validated against the model the effort will actually run on.
            model_switch::apply_reasoning_effort(
                agent,
                session_id.clone(),
                value_id.0.as_ref(),
                ConfigNotice::Send,
            )
            .await?;
        }
        other => {
            return Err(
                acp::Error::invalid_params().data(format!("unknown config option: {other}"))
            );
        }
    }

    let options = agent.acp_config_options_for_session(&session_id).await;
    Ok(acp::SetSessionConfigOptionResponse::new(options))
}
