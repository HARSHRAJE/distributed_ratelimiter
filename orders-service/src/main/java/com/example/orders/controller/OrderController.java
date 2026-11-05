package com.example.orders.controller;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    @GetMapping
    public Map<String, Object> getOrders() {
        return Map.of(
            "message", "Orders service is working",
            "service", "orders-service"
        );
    }

    @PostMapping
    public Map<String, Object> createOrder() {
        return Map.of(
            "message", "Order created successfully"
        );
    }
}
