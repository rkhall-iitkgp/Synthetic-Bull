use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::str::FromStr;
use tokio::sync::mpsc;
use tokio::time::{sleep, Duration};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message as WsMessage};
use url::Url;

#[derive(Clone)]
pub struct SyntheticBullClient {
    tx: mpsc::Sender<Value>,
}

impl SyntheticBullClient {
    /// Starts the WebSocket client loop in the background and returns:
    /// - `SyntheticBullClient`: A handle to send operations (place_order, ping, etc.)
    /// - `mpsc::Receiver<Value>`: A stream of incoming events matching the Python callbacks.
    pub async fn run(
        ws_url: &str,
        api_key: &str,
        guest_mode: bool,
    ) -> (Self, mpsc::Receiver<Value>) {
        let (send_tx, mut send_rx) = mpsc::channel::<Value>(100);
        let (recv_tx, recv_rx) = mpsc::channel::<Value>(100);

        let ws_url = ws_url.to_string();
        let api_key = api_key.to_string();
        
        let client = Self { tx: send_tx };
        
        let recv_tx_clone = recv_tx.clone();

        tokio::spawn(async move {
            let mut backoff = 1.0;
            loop {
                let url = Url::parse(&ws_url).expect("Invalid WebSocket URL");
                
                match connect_async(url).await {
                    Ok((ws_stream, _)) => {
                        let _ = recv_tx_clone.send(json!({ "type": "connect", "ws_url": ws_url })).await;
                        backoff = 1.0; // reset backoff on connect

                        let (mut write, mut read) = ws_stream.split();
                        
                        let login_msg = if guest_mode {
                            json!({ "type": "guest_login" })
                        } else {
                            json!({ "type": "auth", "api_key": &api_key })
                        };

                        if let Ok(body) = serde_json::to_string(&login_msg) {
                            let _ = write.send(WsMessage::Text(body)).await;
                        }

                        loop {
                            tokio::select! {
                                msg = read.next() => {
                                    match msg {
                                        Some(Ok(WsMessage::Text(text))) => {
                                            if let Ok(val) = serde_json::from_str::<Value>(&text) {
                                                if recv_tx_clone.send(val).await.is_err() {
                                                    // Receiver dropped, exit the background loop completely
                                                    return;
                                                }
                                            }
                                        }
                                        Some(Ok(WsMessage::Ping(_))) => {
                                            let _ = write.send(WsMessage::Pong(vec![])).await;
                                        }
                                        Some(Err(e)) => {
                                            let _ = recv_tx_clone.send(json!({ "type": "error", "message": format!("ws read error: {}", e) })).await;
                                            break; // reconnect logic triggers
                                        }
                                        None => {
                                            let _ = recv_tx_clone.send(json!({ "type": "disconnect", "reason": "remote closed connection" })).await;
                                            break; // reconnect logic triggers
                                        }
                                        _ => {} // Ignore other message types for now
                                    }
                                }
                                out_msg = send_rx.recv() => {
                                    if let Some(val) = out_msg {
                                        if let Ok(body) = serde_json::to_string(&val) {
                                            if write.send(WsMessage::Text(body)).await.is_err() {
                                                break;
                                            }
                                        }
                                    } else {
                                        // User dropped the SyntheticBullClient struct. Return completely to close.
                                        let _ = write.close().await;
                                        return;
                                    }
                                }
                            }
                        }
                    }
                    Err(e) => {
                        let _ = recv_tx_clone.send(json!({
                            "type": "error",
                            "message": format!("WebSocket connection failed: {}", e)
                        })).await;
                    }
                }
                
                let _ = recv_tx_clone.send(json!({ "type": "reconnect", "ws_url": ws_url })).await;
                
                // Keep the backoff logic reasonable
                sleep(Duration::from_secs_f64(backoff)).await;
                backoff = (backoff * 1.5).min(30.0);
            }
        });

        (client, recv_rx)
    }

    pub async fn send(&self, msg: Value) -> Result<(), mpsc::error::SendError<Value>> {
        self.tx.send(msg).await
    }

    pub async fn place_limit(&self, symbol: &str, side: &str, price: f64, qty: f64) {
        let _ = self.send(json!({
            "type": "place_order",
            "symbol": symbol,
            "order_type": "limit",
            "side": side,
            "price": price,
            "qty": qty,
        })).await;
    }

    pub async fn place_market(&self, symbol: &str, side: &str, qty: f64) {
        let _ = self.send(json!({
            "type": "place_order",
            "symbol": symbol,
            "order_type": "market",
            "side": side,
            "qty": qty,
        })).await;
    }

    pub async fn cancel(&self, symbol: &str, order_id: i64) {
        let _ = self.send(json!({
            "type": "cancel_order",
            "symbol": symbol,
            "order_id": order_id,
        })).await;
    }

    pub async fn get_symbols(&self) {
        let _ = self.send(json!({ "type": "get_symbols" })).await;
    }

    pub async fn deposit(&self, bot_id: &str, amount: f64) {
        let _ = self.send(json!({ "type": "deposit", "bot_id": bot_id, "amount": amount })).await;
    }

    pub async fn ping(&self) {
        let _ = self.send(json!({ "type": "ping" })).await;
    }
}
