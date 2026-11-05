package com.ratelimiter.policy.redis;

import com.ratelimiter.policy.dto.response.ServiceConfigSnapshot;
import com.ratelimiter.policy.entity.ServiceEntity;
import com.ratelimiter.policy.exception.ResourceNotFoundException;
import com.ratelimiter.policy.repository.ServiceRepository;
import java.util.UUID;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class ServiceConfigSnapshotBuilder {

    private final ServiceRepository serviceRepository;

    public ServiceConfigSnapshotBuilder(ServiceRepository serviceRepository) {
        this.serviceRepository = serviceRepository;
    }

    @Transactional(readOnly = true)
    public ServiceConfigSnapshot build(UUID serviceId) {
        ServiceEntity service = serviceRepository.findById(serviceId)
            .orElseThrow(() -> new ResourceNotFoundException(
                "Service not found: " + serviceId
            ));

        return new ServiceConfigSnapshot(
            service.getServiceKey(),
            service.getConfigVersion(),
            service.getGlobalCapacity(),
            service.getGlobalRefillRate(),
            service.getHardMaxRefillRate()
        );
    }
}
