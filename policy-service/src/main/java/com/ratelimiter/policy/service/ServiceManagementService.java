
package com.ratelimiter.policy.service;

import com.ratelimiter.policy.dto.request.CreateServiceRequest;
import com.ratelimiter.policy.dto.request.UpdateServiceConfigRequest;
import com.ratelimiter.policy.dto.response.ServiceResponse;
import com.ratelimiter.policy.entity.ServiceEntity;
import com.ratelimiter.policy.exception.DuplicateResourceException;
import com.ratelimiter.policy.repository.ServiceRepository;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.ratelimiter.policy.exception.ResourceNotFoundException;

import java.util.List;
import java.util.UUID;

@Service
public class ServiceManagementService {

    private final ServiceRepository serviceRepository;
    private final OutboxService outboxService;

    public ServiceManagementService(
            ServiceRepository serviceRepository,
            OutboxService outboxService) {
        this.serviceRepository = serviceRepository;
        this.outboxService = outboxService;
    }

    @Transactional
    public ServiceResponse createService(CreateServiceRequest request) {

        if (request.globalRefillRate()
                .compareTo(request.hardMaxRefillRate()) > 0) {
            throw new IllegalArgumentException(
                "Global refill rate cannot exceed hard maximum rate"
            );
        }

        if (serviceRepository.existsByServiceKey(request.serviceKey())) {
            throw new DuplicateResourceException(
                "Service already exists: " + request.serviceKey()
            );
        }

        ServiceEntity entity = new ServiceEntity();

        entity.setServiceKey(request.serviceKey());
        entity.setGlobalCapacity(request.globalCapacity());
        entity.setGlobalRefillRate(request.globalRefillRate());
        entity.setHardMaxRefillRate(request.hardMaxRefillRate());
        entity.setAdaptiveEnabled(false);
        entity.setConfigVersion(1L);

        ServiceEntity saved = serviceRepository.saveAndFlush(entity);
        outboxService.publishServiceConfigReconciliation(saved.getId());

        return toResponse(saved);
    }

    @Transactional
    public ServiceResponse updateConfiguration(
            UUID id,
            UpdateServiceConfigRequest request) {

        ServiceEntity entity = serviceRepository.findByIdForUpdate(id)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Service not found: " + id
            ));

        if (request.globalRefillRate()
                .compareTo(entity.getHardMaxRefillRate()) > 0) {
            throw new IllegalArgumentException(
                "Global refill rate cannot exceed hard maximum rate"
            );
        }

        boolean changed =
            !entity.getGlobalCapacity().equals(request.globalCapacity())
            || entity.getGlobalRefillRate()
                .compareTo(request.globalRefillRate()) != 0;

        if (changed) {
            entity.setGlobalCapacity(request.globalCapacity());
            entity.setGlobalRefillRate(request.globalRefillRate());
            entity.setConfigVersion(
                Math.incrementExact(entity.getConfigVersion())
            );
            serviceRepository.saveAndFlush(entity);
            outboxService.publishServiceConfigReconciliation(id);
        }

        return toResponse(entity);
    }

    @Transactional(readOnly = true)
    public List<ServiceResponse> getAllServices() {
        return serviceRepository.findAll()
            .stream()
            .map(this::toResponse)
            .toList();
    }

    @Transactional(readOnly = true)
    public ServiceResponse getService(UUID id) {
        ServiceEntity entity = serviceRepository.findById(id)
            .orElseThrow(() -> new IllegalArgumentException(
                "Service not found: " + id
            ));

        return toResponse(entity);
    }

    private ServiceResponse toResponse(ServiceEntity entity) {
        return new ServiceResponse(
            entity.getId(),
            entity.getServiceKey(),
            entity.getConfigVersion(),
            entity.getGlobalCapacity(),
            entity.getGlobalRefillRate(),
            entity.getHardMaxRefillRate(),
            entity.getAdaptiveEnabled(),
            entity.getCreatedAt(),
            entity.getUpdatedAt()
        );
    }
}
