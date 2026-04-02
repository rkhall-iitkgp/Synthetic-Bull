use reqwest::{Client, Error as ReqwestError};
use serde_json::{json, Value};
use std::collections::HashMap;

#[derive(Debug)]
pub enum AdminApiError {
    Reqwest(ReqwestError),
    Api(String),
}

impl From<ReqwestError> for AdminApiError {
    fn From(err: ReqwestError) -> Self {
        AdminApiError::Reqwest(err)
    }
}

pub struct AdminApiClient {
    pub base_url: String,
    pub timeout: std::time::Duration,
    client: Client,
}

impl AdminApiClient {
    pub fn new(base_url: &str, timeout_secs: u64) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            timeout: std::time::Duration::from_secs(timeout_secs),
            client: Client::builder()
                .timeout(std::time::Duration::from_secs(timeout_secs))
                .build()
                .unwrap(),
        }
    }

    pub async fn create_bot(&self, name: &str) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots", self.base_url);
        let body = json!({ "name": name });
        self.request_post(&url, &body).await
    }

    pub async fn list_bots(&self, skip: u32, limit: u32) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots", self.base_url);
        let params = [("skip", skip.to_string()), ("limit", limit.to_string())];
        self.request_get(&url, Some(&params)).await
    }

    pub async fn get_bot(&self, bot_id: &str) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}", self.base_url, bot_id);
        self.request_get(&url, None).await
    }

    pub async fn get_trades(
        &self,
        bot_id: &str,
        skip: u32,
        limit: u32,
        session_id: Option<&str>,
    ) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/trades", self.base_url, bot_id);
        let mut params = vec![
            ("skip".to_string(), skip.to_string()),
            ("limit".to_string(), limit.to_string()),
        ];
        if let Some(sid) = session_id {
            params.push(("session_id".to_string(), sid.to_string()));
        }
        
        // request_get expects slices of &str or similar, we'll build a hashmap instead
        let req = self.client.get(&url).query(&params);
        self.execute(req).await
    }

    pub async fn get_portfolio(&self, bot_id: &str) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/portfolio", self.base_url, bot_id);
        self.request_get(&url, None).await
    }

    pub async fn get_kpi(
        &self,
        bot_id: &str,
        session_id: Option<&str>,
    ) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/kpi", self.base_url, bot_id);
        let mut req = self.client.get(&url);
        if let Some(sid) = session_id {
            req = req.query(&[("session_id", sid)]);
        }
        self.execute(req).await
    }

    pub async fn deposit(&self, bot_id: &str, amount: f64) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/deposit", self.base_url, bot_id);
        let body = json!({ "amount": amount });
        self.request_post(&url, &body).await
    }

    pub async fn start_session(&self, bot_id: &str) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/sessions/start", self.base_url, bot_id);
        self.request_post(&url, &json!({})).await
    }

    pub async fn stop_session(&self, bot_id: &str) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/sessions/stop", self.base_url, bot_id);
        self.request_post(&url, &json!({})).await
    }

    pub async fn list_sessions(&self, bot_id: &str, skip: u32, limit: u32) -> Result<Value, AdminApiError> {
        let url = format!("{}/api/bots/{}/sessions", self.base_url, bot_id);
        let params = [("skip", skip.to_string()), ("limit", limit.to_string())];
        self.request_get(&url, Some(&params)).await
    }

    async fn request_get(&self, url: &str, params: Option<&[(&str, String)]>) -> Result<Value, AdminApiError> {
        let mut req = self.client.get(url);
        if let Some(p) = params {
            req = req.query(p);
        }
        self.execute(req).await
    }

    async fn request_post(&self, url: &str, body: &Value) -> Result<Value, AdminApiError> {
        let req = self.client.post(url).json(body);
        self.execute(req).await
    }

    async fn execute(&self, builder: reqwest::RequestBuilder) -> Result<Value, AdminApiError> {
        let res = builder.send().await?;
        if res.status().is_success() {
            let text = res.text().await?;
            if text.trim().is_empty() {
                Ok(json!(null))
            } else {
                Ok(serde_json::from_str(&text).unwrap_or(json!({})))
            }
        } else {
            let status = res.status();
            let text = res.text().await.unwrap_or_default();
            Err(AdminApiError::Api(format!("{} error: {}", status, text)))
        }
    }
}
