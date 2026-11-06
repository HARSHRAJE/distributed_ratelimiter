
package com.ratelimiter.policy.service;

import com.ratelimiter.policy.dto.request.CreateServiceRequest;
import com.ratelimiter.policy.dto.request.ExecutionKillSwitchRequest;
import com.ratelimiter.policy.dto.request.AdaptiveControlRequest;
import com.ratelimiter.policy.dto.request.AdaptiveServiceUpdateRequest;
import com.ratelimiter.policy.dto.request.AdaptiveServiceRollbackRequest;
import com.ratelimiter.policy.dto.request.UpdateServiceConfigRequest;
import com.ratelimiter.policy.dto.response.ServiceExecutionStatus;
import com.ratelimiter.policy.dto.response.ServiceRollbackStatus;
import com.ratelimiter.policy.dto.response.ServiceResponse;
import com.ratelimiter.policy.entity.ServiceEntity;
import com.ratelimiter.policy.entity.ServiceExecutionRequestEntity;
import com.ratelimiter.policy.entity.ServiceConfigVersionEntity;
import com.ratelimiter.policy.entity.ServiceRollbackRequestEntity;
import com.ratelimiter.policy.entity.PolicyExecutionControlEntity;
import com.ratelimiter.policy.exception.DuplicateResourceException;
import com.ratelimiter.policy.exception.PolicyConflictException;
import com.ratelimiter.policy.exception.PolicyVersionConflictException;
import com.ratelimiter.policy.repository.ServiceRepository;
import com.ratelimiter.policy.repository.ServiceExecutionRequestRepository;
import com.ratelimiter.policy.repository.ServiceConfigVersionRepository;
import com.ratelimiter.policy.repository.ServiceRollbackRequestRepository;
import com.ratelimiter.policy.repository.PolicyExecutionControlRepository;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.ratelimiter.policy.exception.ResourceNotFoundException;

import java.util.List;
import java.util.UUID;

@Service
public class ServiceManagementService {

    private final ServiceRepository serviceRepository;
    private final ServiceExecutionRequestRepository executionRequestRepository;
    private final ServiceConfigVersionRepository configVersionRepository;
    private final ServiceRollbackRequestRepository rollbackRequestRepository;
    private final PolicyExecutionControlRepository executionControlRepository;
    private final OutboxService outboxService;

    public ServiceManagementService(
            ServiceRepository serviceRepository,
            ServiceExecutionRequestRepository executionRequestRepository,
            ServiceConfigVersionRepository configVersionRepository,
            ServiceRollbackRequestRepository rollbackRequestRepository,
            PolicyExecutionControlRepository executionControlRepository,
            OutboxService outboxService) {
        this.serviceRepository = serviceRepository;
        this.executionRequestRepository = executionRequestRepository;
        this.configVersionRepository = configVersionRepository;
        this.rollbackRequestRepository = rollbackRequestRepository;
        this.executionControlRepository = executionControlRepository;
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
        saveConfigVersion(saved, "INITIAL");
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
            saveConfigVersion(entity, "ADMIN");
            outboxService.publishServiceConfigReconciliation(id);
        }

        return toResponse(entity);
    }

    @Transactional
    public ServiceResponse updateConfigurationByExecution(
            UUID id,
            AdaptiveServiceUpdateRequest request) {
        PolicyExecutionControlEntity control =
            executionControlRepository.findByIdForUpdate("global")
                .orElseThrow(() -> new IllegalStateException(
                    "Global execution kill switch is not initialized"
                ));
        if (control.getKillSwitchActive()) {
            throw new PolicyConflictException(
                "Global execution kill switch is active"
            );
        }
        ServiceEntity entity = serviceRepository.findByIdForUpdate(id)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Service not found: " + id
            ));

        ServiceExecutionRequestEntity previous =
            executionRequestRepository.findById(request.executionId())
                .orElse(null);
        if (previous != null) {
            if (!previous.getServiceId().equals(id)
                    || !previous.getExpectedVersion()
                        .equals(request.expectedConfigVersion())
                    || !previous.getGlobalCapacity()
                        .equals(request.globalCapacity())
                    || previous.getGlobalRefillRate()
                        .compareTo(request.globalRefillRate()) != 0) {
                throw new IllegalArgumentException(
                    "Execution id was already used with different parameters"
                );
            }
            return toResponse(entity);
        }

        if (!Boolean.TRUE.equals(entity.getAdaptiveEnabled())) {
            throw new PolicyConflictException(
                "Adaptive execution is disabled for this service"
            );
        }

        if (!entity.getConfigVersion().equals(request.expectedConfigVersion())) {
            throw new PolicyVersionConflictException(
                "Expected service config version "
                    + request.expectedConfigVersion()
                    + " but found " + entity.getConfigVersion()
            );
        }
        if (request.globalRefillRate()
                .compareTo(entity.getHardMaxRefillRate()) > 0) {
            throw new IllegalArgumentException(
                "Global refill rate cannot exceed hard maximum rate"
            );
        }

        entity.setGlobalCapacity(request.globalCapacity());
        entity.setGlobalRefillRate(request.globalRefillRate());
        entity.setConfigVersion(Math.incrementExact(entity.getConfigVersion()));
        serviceRepository.saveAndFlush(entity);
        saveConfigVersion(entity, "ADAPTIVE_EXECUTION");
        executionRequestRepository.saveAndFlush(
            new ServiceExecutionRequestEntity(
                request.executionId(),
                id,
                request.expectedConfigVersion(),
                entity.getConfigVersion(),
                request.globalCapacity(),
                request.globalRefillRate()
            )
        );
        outboxService.publishServiceConfigReconciliation(id);
        return toResponse(entity);
    }

    @Transactional
    public boolean setExecutionKillSwitch(boolean active) {
        PolicyExecutionControlEntity control =
            executionControlRepository.findByIdForUpdate("global")
                .orElseThrow(() -> new IllegalStateException(
                    "Global execution kill switch is not initialized"
                ));
        control.setKillSwitchActive(active);
        control.setUpdatedAt(java.time.Instant.now());
        executionControlRepository.saveAndFlush(control);
        return control.getKillSwitchActive();
    }

    @Transactional
    public ServiceRollbackStatus rollbackConfigurationByExecution(
            UUID id,
            AdaptiveServiceRollbackRequest request) {
        ServiceEntity entity = serviceRepository.findByIdForUpdate(id)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Service not found: " + id
            ));

        ServiceRollbackRequestEntity previous =
            rollbackRequestRepository.findById(request.rollbackId())
                .orElse(null);
        if (previous != null) {
            if (!previous.getServiceId().equals(id)
                    || !previous.getExpectedActiveVersion()
                        .equals(request.expectedActiveVersion())
                    || !previous.getRestoredFromVersion()
                        .equals(request.restoredFromVersion())) {
                throw new IllegalArgumentException(
                    "Rollback id was already used with different parameters"
                );
            }
            return previous.toStatus();
        }

        if (!entity.getConfigVersion().equals(request.expectedActiveVersion())) {
            throw new PolicyVersionConflictException(
                "Service configuration changed. Expected version: "
                    + request.expectedActiveVersion()
                    + ", current version: " + entity.getConfigVersion()
            );
        }
        if (request.restoredFromVersion()
                >= request.expectedActiveVersion()) {
            throw new PolicyConflictException(
                "Rollback target must be an older service configuration version"
            );
        }
        ServiceConfigVersionEntity target =
            configVersionRepository.findByServiceIdAndConfigVersion(
                id,
                request.restoredFromVersion()
            ).orElseThrow(() -> new ResourceNotFoundException(
                "Service configuration version not found: "
                    + request.restoredFromVersion()
            ));
        if (target.getGlobalRefillRate()
                .compareTo(entity.getHardMaxRefillRate()) > 0) {
            throw new PolicyConflictException(
                "Rollback target exceeds the current administrative hard maximum"
            );
        }

        entity.setGlobalCapacity(target.getGlobalCapacity());
        entity.setGlobalRefillRate(target.getGlobalRefillRate());
        entity.setAdaptiveEnabled(false);
        entity.setConfigVersion(Math.incrementExact(entity.getConfigVersion()));
        serviceRepository.saveAndFlush(entity);
        configVersionRepository.saveAndFlush(
            new ServiceConfigVersionEntity(entity, "ROLLBACK")
        );
        ServiceRollbackRequestEntity rollback =
            rollbackRequestRepository.saveAndFlush(
                new ServiceRollbackRequestEntity(
                    request.rollbackId(),
                    entity,
                    request.expectedActiveVersion(),
                    request.restoredFromVersion()
                )
            );
        outboxService.publishServiceConfigReconciliation(id);
        return rollback.toStatus();
    }

    @Transactional
    public ServiceResponse setAdaptiveControl(
            String serviceKey,
            AdaptiveControlRequest request) {
        ServiceEntity entity = serviceRepository.findByServiceKeyForUpdate(
            serviceKey
        ).orElseThrow(() -> new ResourceNotFoundException(
            "Service not found: " + serviceKey
        ));
        if (!entity.getConfigVersion().equals(request.expectedConfigVersion())) {
            throw new PolicyVersionConflictException(
                "Expected service config version "
                    + request.expectedConfigVersion()
                    + " but found " + entity.getConfigVersion()
            );
        }
        if (!entity.getAdaptiveEnabled().equals(request.enabled())) {
            entity.setAdaptiveEnabled(request.enabled());
            entity.setConfigVersion(Math.incrementExact(entity.getConfigVersion()));
            serviceRepository.saveAndFlush(entity);
            saveConfigVersion(entity, "ADAPTIVE_CONTROL");
            outboxService.publishServiceConfigReconciliation(entity.getId());
        }
        return toResponse(entity);
    }

    @Transactional(readOnly = true)
    public ServiceRollbackStatus getRollbackStatus(
            UUID serviceId,
            UUID rollbackId) {
        ServiceRollbackRequestEntity request =
            rollbackRequestRepository.findById(rollbackId).orElse(null);
        if (request == null || !request.getServiceId().equals(serviceId)) {
            return null;
        }
        return request.toStatus();
    }

    @Transactional(readOnly = true)
    public ServiceResponse getServiceByKey(String serviceKey) {
        ServiceEntity entity = serviceRepository.findByServiceKey(serviceKey)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Service not found: " + serviceKey
            ));
        return toResponse(entity);
    }

    @Transactional(readOnly = true)
    public ServiceExecutionStatus getExecutionStatus(
            UUID serviceId,
            UUID executionId) {
        ServiceExecutionRequestEntity request =
            executionRequestRepository.findById(executionId).orElse(null);
        if (request == null || !request.getServiceId().equals(serviceId)) {
            return new ServiceExecutionStatus(executionId, false, null, null);
        }
        return new ServiceExecutionStatus(
            executionId,
            true,
            request.getResultingVersion(),
            request.getGlobalRefillRate()
        );
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

    private void saveConfigVersion(ServiceEntity entity, String source) {
        configVersionRepository.saveAndFlush(
            new ServiceConfigVersionEntity(entity, source)
        );
    }
}
