use serde::{Deserialize, Serialize};
use serde_json::Value;

pub type Message = Value;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AuthPayload {
    #[serde(rename = "type")]
    pub msg_type: String, // "auth"
    pub api_key: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GuestLoginPayload {
    #[serde(rename = "type")]
    pub msg_type: String, // "guest_login"
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PlaceOrderPayload {
    #[serde(rename = "type")]
    pub msg_type: String, // "place_order"
    pub symbol: String,
    pub order_type: String,
    pub side: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub price: Option<f64>,
    pub qty: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CancelOrderPayload {
    #[serde(rename = "type")]
    pub msg_type: String, // "cancel_order"
    pub symbol: String,
    pub order_id: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GenericMessagePayload {
    #[serde(rename = "type")]
    pub msg_type: String,
    #[serde(flatten)]
    pub extra: Value,
}
