package syntheticbullsdk

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// AdminApiError describes failures from the admin API.
type AdminApiError struct {
	StatusCode int
	Status     string
	Body       string
}

func (e *AdminApiError) Error() string {
	if e == nil {
		return "admin api error"
	}
	if e.StatusCode == 0 {
		return e.Status
	}
	return fmt.Sprintf("%d %s: %s", e.StatusCode, e.Status, e.Body)
}

// AdminApiClient wraps HTTP calls to the admin API.
type AdminApiClient struct {
	BaseURL    string
	Timeout    time.Duration
	HTTPClient *http.Client
}

// NewAdminApiClient builds an admin API client with defaults.
func NewAdminApiClient(baseURL string) *AdminApiClient {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = "http://127.0.0.1:8000"
	}
	return &AdminApiClient{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Timeout: 10 * time.Second,
	}
}

func (c *AdminApiClient) client() *http.Client {
	if c.HTTPClient != nil {
		return c.HTTPClient
	}
	timeout := c.Timeout
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &http.Client{Timeout: timeout}
}

func (c *AdminApiClient) CreateBot(name string) (Message, error) {
	out := Message{}
	err := c.doRequest(http.MethodPost, "/api/bots", Message{"name": name}, nil, &out)
	return out, err
}

func (c *AdminApiClient) ListBots(skip, limit int) ([]Message, error) {
	out := []Message{}
	params := map[string]string{"skip": strconv.Itoa(skip), "limit": strconv.Itoa(limit)}
	err := c.doRequest(http.MethodGet, "/api/bots", nil, params, &out)
	return out, err
}

func (c *AdminApiClient) GetBot(botID string) (Message, error) {
	out := Message{}
	err := c.doRequest(http.MethodGet, "/api/bots/"+botID, nil, nil, &out)
	return out, err
}

func (c *AdminApiClient) GetTrades(botID string, skip, limit int, sessionID string) ([]Message, error) {
	out := []Message{}
	params := map[string]string{"skip": strconv.Itoa(skip), "limit": strconv.Itoa(limit)}
	if strings.TrimSpace(sessionID) != "" {
		params["session_id"] = sessionID
	}
	err := c.doRequest(http.MethodGet, "/api/bots/"+botID+"/trades", nil, params, &out)
	return out, err
}

func (c *AdminApiClient) GetPortfolio(botID string) (Message, error) {
	out := Message{}
	err := c.doRequest(http.MethodGet, "/api/bots/"+botID+"/portfolio", nil, nil, &out)
	return out, err
}

func (c *AdminApiClient) GetKPI(botID string, sessionID string) (Message, error) {
	out := Message{}
	params := map[string]string{}
	if strings.TrimSpace(sessionID) != "" {
		params["session_id"] = sessionID
	}
	err := c.doRequest(http.MethodGet, "/api/bots/"+botID+"/kpi", nil, params, &out)
	return out, err
}

func (c *AdminApiClient) Deposit(botID string, amount float64) (Message, error) {
	out := Message{}
	err := c.doRequest(http.MethodPost, "/api/bots/"+botID+"/deposit", Message{"amount": amount}, nil, &out)
	return out, err
}

func (c *AdminApiClient) StartSession(botID string) (Message, error) {
	out := Message{}
	err := c.doRequest(http.MethodPost, "/api/bots/"+botID+"/sessions/start", nil, nil, &out)
	return out, err
}

func (c *AdminApiClient) StopSession(botID string) (Message, error) {
	out := Message{}
	err := c.doRequest(http.MethodPost, "/api/bots/"+botID+"/sessions/stop", nil, nil, &out)
	return out, err
}

func (c *AdminApiClient) ListSessions(botID string, skip, limit int) ([]Message, error) {
	out := []Message{}
	params := map[string]string{"skip": strconv.Itoa(skip), "limit": strconv.Itoa(limit)}
	err := c.doRequest(http.MethodGet, "/api/bots/"+botID+"/sessions", nil, params, &out)
	return out, err
}

func (c *AdminApiClient) doRequest(method, path string, body any, params map[string]string, out any) error {
	if c == nil {
		return &AdminApiError{Status: "admin client is nil"}
	}
	base := strings.TrimRight(c.BaseURL, "/")
	if base == "" {
		base = "http://127.0.0.1:8000"
	}

	u, err := url.Parse(base + path)
	if err != nil {
		return &AdminApiError{Status: "invalid admin API URL: " + err.Error()}
	}

	q := u.Query()
	for k, v := range params {
		if strings.TrimSpace(v) != "" {
			q.Set(k, v)
		}
	}
	u.RawQuery = q.Encode()

	var reader io.Reader
	if body != nil {
		raw, marshalErr := json.Marshal(body)
		if marshalErr != nil {
			return marshalErr
		}
		reader = bytes.NewReader(raw)
	}

	req, err := http.NewRequest(method, u.String(), reader)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.client().Do(req)
	if err != nil {
		return &AdminApiError{Status: "unable to reach admin API at " + u.String() + ": " + err.Error()}
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return &AdminApiError{StatusCode: resp.StatusCode, Status: resp.Status, Body: string(raw)}
	}

	if len(bytes.TrimSpace(raw)) == 0 || out == nil {
		return nil
	}

	if err := json.Unmarshal(raw, out); err != nil {
		return err
	}
	return nil
}
