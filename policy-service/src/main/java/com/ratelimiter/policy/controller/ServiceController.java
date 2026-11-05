
package com.ratelimiter.policy.controller;

import com.ratelimiter.policy.dto.request.CreateServiceRequest;
import com.ratelimiter.policy.dto.request.UpdateServiceConfigRequest;
import com.ratelimiter.policy.dto.response.ServiceResponse;
import com.ratelimiter.policy.service.ServiceManagementService;

import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/services")
public class ServiceController {

    private final ServiceManagementService service;

    public ServiceController(ServiceManagementService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ServiceResponse create(
            @Valid @RequestBody CreateServiceRequest request) {
        return service.createService(request);
    }

    @GetMapping
    public List<ServiceResponse> getAll() {
        return service.getAllServices();
    }

    @GetMapping("/{id}")
    public ServiceResponse getById(@PathVariable UUID id) {
        return service.getService(id);
    }

    @PutMapping("/{id}/configuration")
    public ServiceResponse updateConfiguration(
            @PathVariable UUID id,
            @Valid @RequestBody UpdateServiceConfigRequest request) {
        return service.updateConfiguration(id, request);
    }
}
