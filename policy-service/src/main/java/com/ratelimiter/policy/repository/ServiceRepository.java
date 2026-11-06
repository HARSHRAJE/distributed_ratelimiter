package com.ratelimiter.policy.repository;

import com.ratelimiter.policy.entity.ServiceEntity;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ServiceRepository extends JpaRepository<ServiceEntity, UUID> {

    Optional<ServiceEntity> findByServiceKey(String serviceKey);

    boolean existsByServiceKey(String serviceKey);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT s FROM ServiceEntity s WHERE s.id = :id")
    Optional<ServiceEntity> findByIdForUpdate(@Param("id") UUID id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT s FROM ServiceEntity s WHERE s.serviceKey = :serviceKey")
    Optional<ServiceEntity> findByServiceKeyForUpdate(
        @Param("serviceKey") String serviceKey
    );
}
