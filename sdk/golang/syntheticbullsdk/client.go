package syntheticbullsdk

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// Message is the exchange JSON payload shape.
type Message map[string]any

// MessageHandler processes an incoming exchange message.
type MessageHandler func(Message)

// ClientConfig controls websocket behavior and handlers.
type ClientConfig struct {
	WSURL             string
	APIKey            string
	GuestMode         bool
	AutoReconnect     bool
	ReconnectMinDelay time.Duration
	ReconnectMaxDelay time.Duration
	HeartbeatInterval time.Duration
	SymbolFilter      map[string]struct{}

	OnMessage    MessageHandler
	OnWelcome    MessageHandler
	OnOrderbook  MessageHandler
	OnTrade      MessageHandler
	OnCandle     MessageHandler
	OnPortfolio  MessageHandler
	OnOpenOrders MessageHandler
	OnAck        MessageHandler
	OnCancelAck  MessageHandler
	OnSymbols    MessageHandler
	OnError      MessageHandler
	OnPong       MessageHandler
	OnConnect    MessageHandler
	OnDisconnect MessageHandler
	OnReconnect  MessageHandler
}

// SyntheticBullClient is a websocket client for exchange interactions.
type SyntheticBullClient struct {
	cfg ClientConfig

	connMu sync.RWMutex
	conn   *websocket.Conn

	sendQueue chan Message
	stopCh    chan struct{}
	stopOnce  sync.Once

	stateMu       sync.RWMutex
	connectedCond *sync.Cond
	welcomedCond  *sync.Cond
	connected     bool
	welcomed      bool

	firstConnectComplete bool

	// Mutable state cached from stream messages.
	UserID             string
	SymbolPrices       map[string]float64
	ShortSellingConfig Message
	LatestPortfolio    Message
	LatestOpenOrders   []Message
}

// NewSyntheticBullClient builds a client with sane defaults.
func NewSyntheticBullClient(cfg ClientConfig) *SyntheticBullClient {
	if !cfg.AutoReconnect {
		// Match the Python SDK default behavior.
		cfg.AutoReconnect = true
	}
	if cfg.ReconnectMinDelay <= 0 {
		cfg.ReconnectMinDelay = 1 * time.Second
	}
	if cfg.ReconnectMaxDelay <= 0 {
		cfg.ReconnectMaxDelay = 30 * time.Second
	}
	if cfg.HeartbeatInterval <= 0 {
		cfg.HeartbeatInterval = 15 * time.Second
	}
	c := &SyntheticBullClient{
		cfg:                 cfg,
		sendQueue:           make(chan Message, 1024),
		stopCh:              make(chan struct{}),
		SymbolPrices:        map[string]float64{},
		ShortSellingConfig:  Message{},
		LatestOpenOrders:    []Message{},
		LatestPortfolio:     nil,
		firstConnectComplete: false,
	}
	c.connectedCond = sync.NewCond(&c.stateMu)
	c.welcomedCond = sync.NewCond(&c.stateMu)
	return c
}

// RunForever starts the websocket loop until stopped or unrecoverable error.
func (c *SyntheticBullClient) RunForever() error {
	if c == nil {
		return errors.New("client is nil")
	}
	if !c.cfg.GuestMode && c.cfg.APIKey == "" {
		return errors.New("api_key is required unless guest_mode=true")
	}
	if c.cfg.WSURL == "" {
		return errors.New("ws_url is required")
	}

	backoff := c.cfg.ReconnectMinDelay
	if backoff < 100*time.Millisecond {
		backoff = 100 * time.Millisecond
	}
	maxBackoff := c.cfg.ReconnectMaxDelay
	if maxBackoff < backoff {
		maxBackoff = backoff
	}

	for {
		if c.isStopped() {
			return nil
		}

		disconnectReason := "connection closed"
		err := c.runSingleConnection()
		if err != nil {
			disconnectReason = err.Error()
		}
		c.setDisconnected()
		c.emit(c.cfg.OnDisconnect, Message{"type": "disconnect", "reason": disconnectReason})

		if c.isStopped() {
			return nil
		}
		if err != nil && !c.cfg.AutoReconnect {
			return err
		}
		if !c.cfg.AutoReconnect {
			return nil
		}

		time.Sleep(backoff)
		backoff *= 2
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
	}
}

func (c *SyntheticBullClient) runSingleConnection() error {
	conn, _, err := websocket.DefaultDialer.Dial(c.cfg.WSURL, nil)
	if err != nil {
		return err
	}

	c.connMu.Lock()
	c.conn = conn
	c.connMu.Unlock()

	c.setConnected()
	c.emit(c.cfg.OnConnect, Message{"type": "connect", "ws_url": c.cfg.WSURL})

	if c.cfg.GuestMode {
		if err := c.sendNow(Message{"type": "guest_login"}); err != nil {
			conn.Close()
			return err
		}
	} else {
		if err := c.sendNow(Message{"type": "auth", "api_key": c.cfg.APIKey}); err != nil {
			conn.Close()
			return err
		}
	}

	if c.firstConnectComplete {
		c.emit(c.cfg.OnReconnect, Message{"type": "reconnect", "ws_url": c.cfg.WSURL})
	}
	c.firstConnectComplete = true

	errCh := make(chan error, 3)
	done := make(chan struct{})
	var doneOnce sync.Once
	closeDone := func() {
		doneOnce.Do(func() { close(done) })
	}
	var wg sync.WaitGroup
	wg.Add(3)

	go func() {
		defer wg.Done()
		errCh <- c.recvLoop(conn, done)
	}()
	go func() {
		defer wg.Done()
		errCh <- c.sendLoop(conn, done)
	}()
	go func() {
		defer wg.Done()
		errCh <- c.keepaliveLoop(done)
	}()

	firstErr := <-errCh
	closeDone()
	_ = conn.Close()
	wg.Wait()
	c.connMu.Lock()
	c.conn = nil
	c.connMu.Unlock()
	c.drainSendQueue()

	if firstErr == nil || errors.Is(firstErr, websocket.ErrCloseSent) {
		return nil
	}
	return firstErr
}

// Stop requests the client loop to end and closes the active websocket.
func (c *SyntheticBullClient) Stop() {
	if c == nil {
		return
	}
	c.stopOnce.Do(func() {
		close(c.stopCh)
	})
	c.connMu.RLock()
	conn := c.conn
	c.connMu.RUnlock()
	if conn != nil {
		_ = conn.Close()
	}
	c.stateMu.Lock()
	c.connected = false
	c.welcomed = false
	c.connectedCond.Broadcast()
	c.welcomedCond.Broadcast()
	c.stateMu.Unlock()
}

// Start runs RunForever in a goroutine and returns a single-result error channel.
func (c *SyntheticBullClient) Start() <-chan error {
	errCh := make(chan error, 1)
	go func() {
		errCh <- c.RunForever()
		close(errCh)
	}()
	return errCh
}

// WaitUntilConnected blocks until the websocket is connected.
func (c *SyntheticBullClient) WaitUntilConnected() {
	c.stateMu.Lock()
	defer c.stateMu.Unlock()
	for !c.connected && !c.isStopped() {
		c.connectedCond.Wait()
	}
}

// WaitUntilWelcome blocks until the welcome message has arrived.
func (c *SyntheticBullClient) WaitUntilWelcome() {
	c.stateMu.Lock()
	defer c.stateMu.Unlock()
	for !c.welcomed && !c.isStopped() {
		c.welcomedCond.Wait()
	}
}

// Send enqueues a payload to be written on the websocket.
func (c *SyntheticBullClient) Send(payload Message) error {
	if c.isStopped() {
		return errors.New("client is stopped")
	}
	c.sendQueue <- payload
	return nil
}

func (c *SyntheticBullClient) PlaceLimit(symbol, side string, price, qty float64) error {
	return c.Send(Message{
		"type":       "place_order",
		"symbol":     symbol,
		"order_type": "limit",
		"side":       side,
		"price":      round(price, 2),
		"qty":        round(qty, 5),
	})
}

func (c *SyntheticBullClient) PlaceMarket(symbol, side string, qty float64) error {
	return c.Send(Message{
		"type":       "place_order",
		"symbol":     symbol,
		"order_type": "market",
		"side":       side,
		"qty":        round(qty, 5),
	})
}

func (c *SyntheticBullClient) Cancel(symbol string, orderID int) error {
	return c.Send(Message{
		"type":     "cancel_order",
		"symbol":   symbol,
		"order_id": orderID,
	})
}

func (c *SyntheticBullClient) GetSymbols() error {
	return c.Send(Message{"type": "get_symbols"})
}

func (c *SyntheticBullClient) Deposit(botID string, amount float64) error {
	return c.Send(Message{"type": "deposit", "bot_id": botID, "amount": amount})
}

func (c *SyntheticBullClient) Ping() error {
	return c.Send(Message{"type": "ping"})
}

func (c *SyntheticBullClient) recvLoop(conn *websocket.Conn, done <-chan struct{}) error {
	for {
		select {
		case <-done:
			return nil
		default:
		}
		if c.isStopped() {
			return nil
		}
		_, raw, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		var msg Message
		if err := json.Unmarshal(raw, &msg); err != nil {
			c.emit(c.cfg.OnError, Message{"type": "error", "message": "message decode failure: " + err.Error()})
			continue
		}
		c.handleMessage(msg)
	}
}

func (c *SyntheticBullClient) sendLoop(conn *websocket.Conn, done <-chan struct{}) error {
	for {
		select {
		case <-c.stopCh:
			return nil
		case <-done:
			return nil
		case payload := <-c.sendQueue:
			raw, err := json.Marshal(payload)
			if err != nil {
				return err
			}
			if err := conn.WriteMessage(websocket.TextMessage, raw); err != nil {
				return err
			}
		}
	}
}

func (c *SyntheticBullClient) keepaliveLoop(done <-chan struct{}) error {
	if c.cfg.HeartbeatInterval <= 0 {
		return nil
	}
	ticker := time.NewTicker(c.cfg.HeartbeatInterval)
	defer ticker.Stop()
	for {
		select {
		case <-c.stopCh:
			return nil
		case <-done:
			return nil
		case <-ticker.C:
			if err := c.Send(Message{"type": "ping"}); err != nil {
				return err
			}
		}
	}
}

func (c *SyntheticBullClient) sendNow(payload Message) error {
	c.connMu.RLock()
	conn := c.conn
	c.connMu.RUnlock()
	if conn == nil {
		return errors.New("websocket is not connected")
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return conn.WriteMessage(websocket.TextMessage, raw)
}

func (c *SyntheticBullClient) handleMessage(msg Message) {
	msgType, _ := msg["type"].(string)

	if (msgType == "orderbook" || msgType == "trade" || msgType == "candle") && len(c.cfg.SymbolFilter) > 0 {
		symbol, _ := msg["symbol"].(string)
		if _, ok := c.cfg.SymbolFilter[symbol]; !ok {
			return
		}
	}

	if msgType == "welcome" {
		c.stateMu.Lock()
		if userID, ok := msg["user_id"].(string); ok {
			c.UserID = userID
		}
		c.SymbolPrices = map[string]float64{}
		if symbols, ok := msg["symbols"].([]any); ok {
			for _, entry := range symbols {
				item, ok := entry.(map[string]any)
				if !ok {
					continue
				}
				symbol, _ := item["symbol"].(string)
				if symbol == "" {
					continue
				}
				price := asFloat64(item["price"])
				c.SymbolPrices[symbol] = price
			}
		}
		if shortCfg, ok := msg["short_selling"].(map[string]any); ok {
			c.ShortSellingConfig = Message(shortCfg)
		} else {
			c.ShortSellingConfig = Message{}
		}
		c.welcomed = true
		c.welcomedCond.Broadcast()
		c.stateMu.Unlock()
	}

	if msgType == "portfolio" {
		c.stateMu.Lock()
		c.LatestPortfolio = msg
		c.stateMu.Unlock()
	}

	if msgType == "open_orders" {
		orders := []Message{}
		if rawOrders, ok := msg["orders"].([]any); ok {
			for _, entry := range rawOrders {
				if item, ok := entry.(map[string]any); ok {
					orders = append(orders, Message(item))
				}
			}
		}
		c.stateMu.Lock()
		c.LatestOpenOrders = orders
		c.stateMu.Unlock()
	}

	c.emit(c.cfg.OnMessage, msg)

	switch msgType {
	case "welcome":
		c.emit(c.cfg.OnWelcome, msg)
	case "orderbook":
		c.emit(c.cfg.OnOrderbook, msg)
	case "trade":
		c.emit(c.cfg.OnTrade, msg)
	case "candle":
		c.emit(c.cfg.OnCandle, msg)
	case "portfolio":
		c.emit(c.cfg.OnPortfolio, msg)
	case "open_orders":
		c.emit(c.cfg.OnOpenOrders, msg)
	case "ack":
		c.emit(c.cfg.OnAck, msg)
	case "cancel_ack":
		c.emit(c.cfg.OnCancelAck, msg)
	case "symbols":
		c.emit(c.cfg.OnSymbols, msg)
	case "error":
		c.emit(c.cfg.OnError, msg)
	case "pong":
		c.emit(c.cfg.OnPong, msg)
	}
}

func (c *SyntheticBullClient) emit(handler MessageHandler, msg Message) {
	if handler == nil {
		return
	}
	defer func() {
		if r := recover(); r != nil {
			fmt.Printf("[SyntheticBullClient] Handler panic for '%v': %v\n", msg["type"], r)
		}
	}()
	handler(msg)
}

func (c *SyntheticBullClient) setConnected() {
	c.stateMu.Lock()
	c.connected = true
	c.connectedCond.Broadcast()
	c.stateMu.Unlock()
}

func (c *SyntheticBullClient) setDisconnected() {
	c.stateMu.Lock()
	c.connected = false
	c.welcomed = false
	c.connectedCond.Broadcast()
	c.welcomedCond.Broadcast()
	c.stateMu.Unlock()
}

func (c *SyntheticBullClient) isStopped() bool {
	select {
	case <-c.stopCh:
		return true
	default:
		return false
	}
}

func (c *SyntheticBullClient) drainSendQueue() {
	for {
		select {
		case <-c.sendQueue:
		default:
			return
		}
	}
}

func round(v float64, places int) float64 {
	p := math.Pow(10, float64(places))
	return math.Round(v*p) / p
}

func asFloat64(v any) float64 {
	switch x := v.(type) {
	case float64:
		return x
	case float32:
		return float64(x)
	case int:
		return float64(x)
	case int32:
		return float64(x)
	case int64:
		return float64(x)
	case json.Number:
		f, _ := x.Float64()
		return f
	default:
		return 0
	}
}
