package main
import (
    "fmt"
    "net"
    "time"
)
func testNetConnection() {
    fmt.Println("dialing 127.0.0.1:8000 ...")
    conn, err := net.DialTimeout("tcp", "127.0.0.1:8000", 3*time.Second)
    if err != nil {
        fmt.Println("connect error:", err)
    } else {
        fmt.Println("connected successfully")
        conn.Close()
    }
}
