package ramify

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

func runtimeDirectory(root string) string {
	if override := os.Getenv("RAMIFY_DATA_DIR"); override != "" {
		if abs, err := filepath.Abs(override); err == nil {
			return abs
		}
		return override
	}
	return filepath.Join(root, "runtime_data")
}

func readJSONFile(path string, dst any) error {
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	return dec.Decode(dst)
}

func readJSONL(path string) ([]map[string]any, error) {
	f, err := os.Open(path)
	if os.IsNotExist(err) {
		return make([]map[string]any, 0), nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	rows := make([]map[string]any, 0)
	s := bufio.NewScanner(f)
	line := 0
	for s.Scan() {
		line++
		raw := bytes.TrimSpace(s.Bytes())
		if len(raw) == 0 {
			continue
		}
		var row map[string]any
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.UseNumber()
		if err := dec.Decode(&row); err != nil {
			return nil, fmt.Errorf("invalid %s at line %d: %w", filepath.Base(path), line, err)
		}
		rows = append(rows, row)
	}
	if err := s.Err(); err != nil {
		return nil, err
	}
	return rows, nil
}

func atomicWrite(path string, content []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".ramify-*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if _, err := f.Write(content); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func encodeJSON(value any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	if err := enc.Encode(value); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func encodeJSONL(rows []map[string]any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	for _, row := range rows {
		if err := enc.Encode(row); err != nil {
			return nil, err
		}
	}
	return buf.Bytes(), nil
}

func (s *Server) loadRuntimeState() error {
	if err := os.MkdirAll(s.runtimeDir, 0o700); err != nil {
		return err
	}
	receipts, err := readJSONL(filepath.Join(s.runtimeDir, "receipts.jsonl"))
	if err != nil {
		return fmt.Errorf("read receipt ledger: %w", err)
	}
	actions, err := readJSONL(filepath.Join(s.runtimeDir, "actions.jsonl"))
	if err != nil {
		return fmt.Errorf("read action ledger: %w", err)
	}
	cartPayload := map[string]any{"lines": []any{}, "orders": []any{}, "requisitions": []any{}}
	if err := readJSONFile(filepath.Join(s.runtimeDir, "cart.json"), &cartPayload); err != nil {
		return fmt.Errorf("read cart state: %w", err)
	}
	custom := map[string]map[string]any{}
	if err := readJSONFile(filepath.Join(s.runtimeDir, "agent_profiles.json"), &custom); err != nil {
		return fmt.Errorf("read agent profiles: %w", err)
	}
	toRows := func(v any) []map[string]any {
		out := make([]map[string]any, 0)
		for _, raw := range arr(v) {
			if row := obj(raw); row != nil {
				out = append(out, row)
			}
		}
		return out
	}
	state.mu.Lock()
	state.receipts = receipts
	state.actions = actions
	state.cart = toRows(cartPayload["lines"])
	state.orders = toRows(cartPayload["orders"])
	state.requisitions = toRows(cartPayload["requisitions"])
	state.customAgents = custom
	if state.customAgents == nil {
		state.customAgents = map[string]map[string]any{}
	}
	state.mu.Unlock()
	return nil
}

func (s *Server) persistReceipts() error {
	state.mu.Lock()
	rows := cloneRows(state.receipts)
	state.mu.Unlock()
	b, err := encodeJSONL(rows)
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(s.runtimeDir, "receipts.jsonl"), b)
}

func (s *Server) persistActions() error {
	state.mu.Lock()
	rows := cloneRows(state.actions)
	state.mu.Unlock()
	b, err := encodeJSONL(rows)
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(s.runtimeDir, "actions.jsonl"), b)
}

func (s *Server) persistCart() error {
	state.mu.Lock()
	payload := map[string]any{
		"lines": cloneRows(state.cart), "orders": cloneRows(state.orders), "requisitions": cloneRows(state.requisitions),
	}
	state.mu.Unlock()
	b, err := encodeJSON(payload)
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(s.runtimeDir, "cart.json"), b)
}

func (s *Server) persistAgents() error {
	state.mu.Lock()
	payload := map[string]map[string]any{}
	for ref, p := range state.customAgents {
		payload[ref] = copyMap(p)
	}
	state.mu.Unlock()
	b, err := encodeJSON(payload)
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(s.runtimeDir, "agent_profiles.json"), b)
}
