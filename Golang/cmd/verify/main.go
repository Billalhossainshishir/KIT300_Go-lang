package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"ramifyos/internal/ramify"
)

func readInput() ([]byte, error) {
	if len(os.Args) > 1 {
		return os.ReadFile(os.Args[1])
	}
	info, err := os.Stdin.Stat()
	if err != nil {
		return nil, err
	}
	if info.Mode()&os.ModeCharDevice != 0 {
		return nil, fmt.Errorf("usage: RAMIFY-Verify <receipt.json> or pipe JSON on stdin")
	}
	return io.ReadAll(os.Stdin)
}
func findRoot() string {
	wd, _ := os.Getwd()
	if abs, err := filepath.Abs(wd); err == nil {
		wd = abs
	}
	if _, err := os.Stat(filepath.Join(wd, "data", "demo_seed.json")); err == nil {
		return wd
	}
	if exe, err := os.Executable(); err == nil {
		d := filepath.Dir(exe)
		for i := 0; i < 5; i++ {
			if _, e := os.Stat(filepath.Join(d, "data", "demo_seed.json")); e == nil {
				return d
			}
			p := filepath.Dir(d)
			if p == d {
				break
			}
			d = p
		}
	}
	return wd
}
func main() {
	b, err := readInput()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	var receipt map[string]any
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	if err := dec.Decode(&receipt); err != nil {
		fmt.Fprintln(os.Stderr, "invalid receipt JSON:", err)
		os.Exit(1)
	}
	srv, err := ramify.New(findRoot())
	if err != nil {
		fmt.Fprintln(os.Stderr, "RAMIFY verifier startup failed:", err)
		os.Exit(1)
	}
	report := srv.VerifyReceipt(receipt)
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(report)
	if ok, _ := report["verified"].(bool); !ok {
		os.Exit(2)
	}
}
