"""SQLAlchemy models for all database tables."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, 
    Boolean, Text, Index, CheckConstraint, BigInteger, Date, Numeric
)
from sqlalchemy.orm import relationship
from app.database import Base


# ============================================================================
# TRANSACTIONAL TABLES (10 tables)
# ============================================================================

class User(Base):
    """User accounts."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True)
    total_trips = Column(Integer, default=0)
    
    # Relationships
    trips = relationship("Trip", back_populates="user", foreign_keys="Trip.user_id")
    ratings_given = relationship("Rating", back_populates="user", foreign_keys="Rating.user_id")
    support_tickets = relationship("SupportTicket", back_populates="user")
    
    __table_args__ = (
        Index("idx_users_email_active", "email", "is_active"),
    )


class Driver(Base):
    """Driver accounts."""
    __tablename__ = "drivers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=False)
    license_number = Column(String(100), unique=True, nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"))
    rating = Column(Float, default=5.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    total_trips = Column(Integer, default=0)
    total_earnings = Column(Numeric(10, 2), default=0)
    
    # Relationships
    region = relationship("Region", back_populates="drivers")
    vehicle = relationship("Vehicle", back_populates="driver")
    trips = relationship("Trip", back_populates="driver")
    ratings_received = relationship("Rating", back_populates="driver", foreign_keys="Rating.driver_id")
    
    __table_args__ = (
        Index("idx_drivers_region_active", "region_id", "is_active"),
    )


class Region(Base):
    """Geographic regions."""
    __tablename__ = "regions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "USNC", "EU", "APAC"
    country = Column(String(100), nullable=False)
    city = Column(String(100))
    timezone = Column(String(50), default="UTC")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    drivers = relationship("Driver", back_populates="region")
    trips = relationship("Trip", back_populates="region")


class Vehicle(Base):
    """Vehicles used by drivers."""
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True, index=True)
    license_plate = Column(String(50), unique=True, nullable=False)
    make = Column(String(100), nullable=False)  # Toyota, Honda, etc.
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(50))
    vehicle_type = Column(String(50), nullable=False)  # sedan, suv, premium
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    driver = relationship("Driver", back_populates="vehicle", uselist=False)
    trips = relationship("Trip", back_populates="vehicle")


class Trip(Base):
    """Trip records."""
    __tablename__ = "trips"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    
    pickup_location = Column(String(255), nullable=False)
    dropoff_location = Column(String(255), nullable=False)
    pickup_time = Column(DateTime, nullable=False, index=True)
    dropoff_time = Column(DateTime)
    
    distance_km = Column(Float, nullable=False)
    duration_minutes = Column(Integer)
    base_fare = Column(Numeric(10, 2), nullable=False)
    surge_multiplier = Column(Float, default=1.0)
    total_fare = Column(Numeric(10, 2), nullable=False)
    
    status = Column(String(50), nullable=False, default="completed")  # requested, ongoing, completed, cancelled
    payment_id = Column(Integer, ForeignKey("payments.id"))
    promotion_id = Column(Integer, ForeignKey("promotions.id"))
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="trips", foreign_keys=[user_id])
    driver = relationship("Driver", back_populates="trips")
    vehicle = relationship("Vehicle", back_populates="trips")
    region = relationship("Region", back_populates="trips")
    payment = relationship("Payment", back_populates="trip")
    promotion = relationship("Promotion", back_populates="trips")
    rating = relationship("Rating", back_populates="trip", uselist=False)
    
    __table_args__ = (
        Index("idx_trips_region_date", "region_id", "pickup_time"),
        Index("idx_trips_user_date", "user_id", "pickup_time"),
        Index("idx_trips_status", "status"),
    )


class Payment(Base):
    """Payment transactions."""
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(50), nullable=False)  # credit_card, debit_card, cash, wallet
    status = Column(String(50), nullable=False, default="completed")  # pending, completed, failed, refunded
    transaction_id = Column(String(255), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    trip = relationship("Trip", back_populates="payment", uselist=False)
    
    __table_args__ = (
        Index("idx_payments_status_date", "status", "created_at"),
    )


class Promotion(Base):
    """Promotional campaigns."""
    __tablename__ = "promotions"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    discount_type = Column(String(50), nullable=False)  # percentage, fixed_amount
    discount_value = Column(Numeric(10, 2), nullable=False)
    max_discount = Column(Numeric(10, 2))
    min_trip_amount = Column(Numeric(10, 2))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    trips = relationship("Trip", back_populates="promotion")
    
    __table_args__ = (
        Index("idx_promotions_active_dates", "is_active", "start_date", "end_date"),
    )


class Rating(Base):
    """Trip ratings."""
    __tablename__ = "ratings"
    
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=False, index=True)
    
    user_rating = Column(Integer, nullable=False)  # 1-5
    driver_rating = Column(Integer, nullable=False)  # 1-5
    user_comment = Column(Text)
    driver_comment = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    trip = relationship("Trip", back_populates="rating")
    user = relationship("User", back_populates="ratings_given", foreign_keys=[user_id])
    driver = relationship("Driver", back_populates="ratings_received", foreign_keys=[driver_id])
    
    __table_args__ = (
        CheckConstraint('user_rating >= 1 AND user_rating <= 5'),
        CheckConstraint('driver_rating >= 1 AND driver_rating <= 5'),
        Index("idx_ratings_driver_date", "driver_id", "created_at"),
    )


class SurgePricing(Base):
    """Surge pricing events."""
    __tablename__ = "surge_pricing"
    
    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    area = Column(String(255), nullable=False)
    surge_multiplier = Column(Float, nullable=False)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime)
    reason = Column(String(255))  # high_demand, event, weather, etc.
    is_active = Column(Boolean, default=True)
    
    __table_args__ = (
        Index("idx_surge_region_time", "region_id", "start_time"),
        CheckConstraint('surge_multiplier >= 1.0'),
    )


class SupportTicket(Base):
    """Customer support tickets."""
    __tablename__ = "support_tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)  # payment, driver, safety, other
    status = Column(String(50), nullable=False, default="open")  # open, in_progress, resolved, closed
    priority = Column(String(50), default="medium")  # low, medium, high, urgent
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", back_populates="support_tickets")
    
    __table_args__ = (
        Index("idx_tickets_status_priority", "status", "priority"),
        Index("idx_tickets_category_date", "category", "created_at"),
    )


# ============================================================================
# FLATTENED ANALYTICS TABLES (2 tables)
# ============================================================================

class TripMetricsDaily(Base):
    """Daily aggregated trip metrics (flattened for analytics)."""
    __tablename__ = "trip_metrics_daily"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    
    total_trips = Column(Integer, default=0)
    completed_trips = Column(Integer, default=0)
    cancelled_trips = Column(Integer, default=0)
    
    total_revenue = Column(Numeric(12, 2), default=0)
    avg_trip_distance = Column(Float, default=0)
    avg_trip_duration = Column(Float, default=0)
    avg_fare = Column(Numeric(10, 2), default=0)
    
    unique_users = Column(Integer, default=0)
    unique_drivers = Column(Integer, default=0)
    
    surge_trips = Column(Integer, default=0)
    promo_trips = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_metrics_region_date", "region_id", "date"),
    )


class RegionRevenueSummary(Base):
    """Regional revenue summary (flattened for business analytics)."""
    __tablename__ = "region_revenue_summary"
    
    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)
    
    total_revenue = Column(Numeric(12, 2), default=0)
    total_trips = Column(Integer, default=0)
    total_distance_km = Column(Float, default=0)
    
    active_users = Column(Integer, default=0)
    active_drivers = Column(Integer, default=0)
    
    avg_rating = Column(Float, default=0)
    support_tickets = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_revenue_region_year_month", "region_id", "year", "month"),
    )


# ============================================================================
# SYSTEM TABLES
# ============================================================================

class GoldenQuery(Base):
    """Validated golden queries for comparison."""
    __tablename__ = "golden_queries"
    
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    sql_query = Column(Text, nullable=False)
    expected_result_hash = Column(String(255))  # Hash of expected result for comparison
    description = Column(Text)
    category = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_validated = Column(DateTime)
    
    __table_args__ = (
        Index("idx_golden_category_active", "category", "is_active"),
    )


class MetadataIndex(Base):
    """Metadata index for tables and columns (backup for OpenSearch)."""
    __tablename__ = "metadata_index"
    
    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String(255), nullable=False, index=True)
    column_name = Column(String(255), index=True)
    
    display_name = Column(String(255))
    description = Column(Text)
    business_term = Column(String(255))  # e.g., "USNC" -> "US and Canada"
    data_type = Column(String(100))
    is_metric = Column(Boolean, default=False)
    metric_definition = Column(Text)
    example_values = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_metadata_table_column", "table_name", "column_name"),
    )


class QueryHistory(Base):
    """History of queries executed by AI."""
    __tablename__ = "query_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_question = Column(Text, nullable=False)
    generated_sql = Column(Text)
    execution_result = Column(Text)
    confidence_score = Column(Float)
    trust_score = Column(Float)
    agent_used = Column(String(100))  # sql_agent, doc_agent
    error_message = Column(Text)
    execution_time_ms = Column(Integer)
    
    is_reviewed = Column(Boolean, default=False)
    review_feedback = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index("idx_query_history_date", "created_at"),
    )
