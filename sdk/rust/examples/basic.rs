use synthetic_bull_sdk::{AdminApiClient, SyntheticBullClient};
use tokio::time::{sleep, Duration};

#[tokio::main]
async fn main() {
    println!("Initializing Synthetic Bull Rust SDK Example...");

    // 1. Test Admin API
    let admin = AdminApiClient::new("http://127.0.0.1:8000", 10);
    match admin.list_bots(0, 10).await {
        Ok(res) => println!("Admin API list_bots success: {:?}", res),
        Err(e) => println!("Admin API returned an error (expected if backend offline): {:?}", e),
    }

    // 2. Test Client WebSocket API
    let ws_url = "ws://127.0.0.1:8000/ws";
    let api_key = "example-api-key";

    println!("Connecting WebSocket to {} (this will retry if offline)...", ws_url);
    let (client, mut rx) = SyntheticBullClient::run(ws_url, api_key, true).await;

    // Spawn a task to listen to events
    let handler = tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            let msg_type = msg.get("type").and_then(|t| t.as_str()).unwrap_or("unknown");
            println!("[WS Event] type={}: {:?}", msg_type, msg);
        }
        println!("[WS loop exited]");
    });

    // Send a sample ping
    sleep(Duration::from_secs(2)).await;
    client.ping().await;

    // Wait a bit to show it processing before exiting (or keep it running)
    sleep(Duration::from_secs(5)).await;
    println!("Exiting example.");
}
