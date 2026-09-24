package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	"ramifyos/internal/ramify"
)

func looksLikeProjectRoot(root string) bool {
	for _, rel := range []string{filepath.Join("data", "demo_seed.json"), filepath.Join("frontend", "pages", "console.html"), "VERSION.txt"} {
		if _, err := os.Stat(filepath.Join(root, rel)); err != nil {
			return false
		}
	}
	return true
}

func defaultProjectRoot() string {
	if wd, err := os.Getwd(); err == nil {
		if abs, err := filepath.Abs(wd); err == nil && looksLikeProjectRoot(abs) {
			return abs
		}
	}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		for i := 0; i < 5; i++ {
			if looksLikeProjectRoot(dir) {
				return dir
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	wd, _ := os.Getwd()
	return wd
}

func browserURL(host string, port int) string {
	if host == "0.0.0.0" || host == "::" || host == "" {
		host = "127.0.0.1"
	}
	if host == "::1" {
		return fmt.Sprintf("http://[::1]:%d/shop", port)
	}
	return fmt.Sprintf("http://%s:%d/shop", host, port)
}

func openBrowser(url string) error {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	return cmd.Start()
}

func setupLogging(runtimeDir string) io.Closer {
	path := filepath.Join(runtimeDir, "ramify.log")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if err != nil {
		return nil
	}
	if runtime.GOOS == "windows" {
		log.SetOutput(f)
	} else {
		log.SetOutput(io.MultiWriter(os.Stderr, f))
	}
	return f
}

func main() {
	host := flag.String("host", "127.0.0.1", "bind host")
	port := flag.Int("port", 0, "bind port; 0 selects a free local port")
	root := flag.String("root", "", "project root; normally omitted")
	noBrowser := flag.Bool("no-browser", false, "start without opening the browser")
	flag.Parse()
	if *root == "" {
		*root = defaultProjectRoot()
	}
	abs, err := filepath.Abs(*root)
	if err != nil {
		log.Fatal(err)
	}
	srv, err := ramify.New(abs)
	if err != nil {
		log.Fatalf("RAMIFY startup failed: %v", err)
	}
	if closer := setupLogging(srv.RuntimeDir()); closer != nil {
		defer closer.Close()
	}
	ln, err := net.Listen("tcp", fmt.Sprintf("%s:%d", *host, *port))
	if err != nil {
		log.Fatalf("RAMIFY could not start: %v", err)
	}
	defer ln.Close()
	actualPort := ln.Addr().(*net.TCPAddr).Port
	url := browserURL(*host, actualPort)
	log.Printf("RAMIFY OS Go Final Runtime")
	log.Printf("Local interface: %s", url)
	server := &http.Server{Handler: srv.Handler()}
	if !*noBrowser {
		if err := openBrowser(url); err != nil {
			log.Printf("Open manually: %s", url)
		}
	}
	if err := server.Serve(ln); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
