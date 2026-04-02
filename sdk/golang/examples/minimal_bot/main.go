package main

import (
	"fmt"
	"log"
	"os"

	sdk "synthetic-bull-sdk-go/syntheticbullsdk"
)

type MinimalBot struct {
	symbol    string
	orderSent bool
	client    *sdk.SyntheticBullClient
}

func NewMinimalBot() *MinimalBot {
	bot := &MinimalBot{
		symbol: getenv("BOT_SYMBOL", "AAPL"),
	}

	bot.client = sdk.NewSyntheticBullClient(sdk.ClientConfig{
		WSURL:         getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001"),
		APIKey:        os.Getenv("BOT_API_KEY"),
		AutoReconnect: true,
		OnWelcome:     bot.onWelcome,
		OnOrderbook:   bot.onOrderbook,
		OnAck:         bot.onAck,
		OnError:       bot.onError,
	})

	return bot
}

func (b *MinimalBot) onWelcome(msg sdk.Message) {
	fmt.Printf("[MinimalBot] Connected as %v\n", msg["user_id"])
	if err := b.client.GetSymbols(); err != nil {
		log.Printf("[MinimalBot] get_symbols failed: %v", err)
	}
}

func (b *MinimalBot) onOrderbook(msg sdk.Message) {
	symbol, _ := msg["symbol"].(string)
	if symbol != b.symbol || b.orderSent {
		return
	}
	mid := toFloat(msg["mid"])
	if mid <= 0 {
		return
	}

	// Demo strategy: place one passive buy at 0.1% below mid.
	bid := mid * 0.999
	if err := b.client.PlaceLimit(b.symbol, "buy", bid, 0.01); err != nil {
		log.Printf("[MinimalBot] place_limit failed: %v", err)
		return
	}
	b.orderSent = true
}

func (b *MinimalBot) onAck(msg sdk.Message) {
	fmt.Printf("[MinimalBot] Order accepted: %+v\n", msg)
}

func (b *MinimalBot) onError(msg sdk.Message) {
	fmt.Printf("[MinimalBot] Exchange error: %v\n", msg["message"])
}

func (b *MinimalBot) Run() error {
	return b.client.RunForever()
}

func main() {
	bot := NewMinimalBot()
	if err := bot.Run(); err != nil {
		log.Fatal(err)
	}
}

func getenv(key, fallback string) string {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	return v
}

func toFloat(v any) float64 {
	switch x := v.(type) {
	case float64:
		return x
	case float32:
		return float64(x)
	case int:
		return float64(x)
	case int64:
		return float64(x)
	default:
		return 0
	}
}
