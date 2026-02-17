"""Seed database with realistic data (1000 records per table)."""
import random
from datetime import datetime, timedelta
from decimal import Decimal
from faker import Faker
from sqlalchemy.orm import Session

from app.database import SyncSessionLocal, init_db_sync
from app.models import (
    User, Driver, Region, Vehicle, Trip, Payment, Promotion,
    Rating, SurgePricing, SupportTicket, TripMetricsDaily,
    RegionRevenueSummary, GoldenQuery, MetadataIndex
)

fake = Faker()


def seed_regions(db: Session):
    """Seed regions with region codes."""
    print("Seeding regions...")
    regions_data = [
        {"name": "US and Canada", "code": "USNC", "country": "USA", "city": "New York", "timezone": "America/New_York"},
        {"name": "United States West", "code": "USW", "country": "USA", "city": "San Francisco", "timezone": "America/Los_Angeles"},
        {"name": "Europe", "code": "EU", "country": "UK", "city": "London", "timezone": "Europe/London"},
        {"name": "Asia Pacific", "code": "APAC", "country": "Singapore", "city": "Singapore", "timezone": "Asia/Singapore"},
        {"name": "Latin America", "code": "LATAM", "country": "Brazil", "city": "Sao Paulo", "timezone": "America/Sao_Paulo"},
    ]
    
    regions = []
    for data in regions_data:
        region = Region(**data)
        db.add(region)
        regions.append(region)
    
    db.commit()
    print(f"Created {len(regions)} regions")
    return regions


def seed_users(db: Session, count: int = 1000):
    """Seed users."""
    print(f"Seeding {count} users...")
    users = []
    
    for i in range(count):
        user = User(
            email=fake.unique.email(),
            name=fake.name(),
            phone=fake.phone_number()[:50],
            created_at=fake.date_time_between(start_date="-2y", end_date="now"),
            is_active=random.choice([True, True, True, False]),  # 75% active
            total_trips=random.randint(0, 100)
        )
        users.append(user)
    
    db.bulk_save_objects(users)
    db.commit()
    print(f"Created {count} users")
    return users


def seed_vehicles(db: Session, count: int = 1000):
    """Seed vehicles."""
    print(f"Seeding {count} vehicles...")
    vehicles = []
    
    makes = ["Toyota", "Honda", "Ford", "Tesla", "BMW", "Mercedes", "Audi", "Hyundai", "Nissan", "Chevrolet"]
    models = ["Camry", "Accord", "Model 3", "Civic", "Corolla", "Prius", "X5", "E-Class", "A4", "Elantra"]
    colors = ["White", "Black", "Silver", "Gray", "Blue", "Red"]
    vehicle_types = ["sedan", "suv", "premium", "economy"]
    
    for i in range(count):
        vehicle = Vehicle(
            license_plate=fake.unique.license_plate()[:50],
            make=random.choice(makes),
            model=random.choice(models),
            year=random.randint(2015, 2024),
            color=random.choice(colors),
            vehicle_type=random.choice(vehicle_types),
            is_active=random.choice([True, True, True, False]),
            created_at=fake.date_time_between(start_date="-2y", end_date="now")
        )
        vehicles.append(vehicle)
    
    db.bulk_save_objects(vehicles)
    db.commit()
    print(f"Created {count} vehicles")
    return vehicles


def seed_drivers(db: Session, regions: list, vehicles: list, count: int = 1000):
    """Seed drivers."""
    print(f"Seeding {count} drivers...")
    drivers = []
    
    for i in range(count):
        vehicle = vehicles[i] if i < len(vehicles) else None
        driver = Driver(
            name=fake.name(),
            email=fake.unique.email(),
            phone=fake.phone_number()[:50],
            license_number=fake.unique.bothify(text="??####????")[:100],
            region_id=random.choice(regions).id,
            vehicle_id=vehicle.id if vehicle else None,
            rating=round(random.uniform(3.5, 5.0), 2),
            is_active=random.choice([True, True, True, False]),
            created_at=fake.date_time_between(start_date="-2y", end_date="now"),
            total_trips=random.randint(0, 500),
            total_earnings=Decimal(str(round(random.uniform(1000, 50000), 2)))
        )
        drivers.append(driver)
    
    db.bulk_save_objects(drivers)
    db.commit()
    print(f"Created {count} drivers")
    return drivers


def seed_promotions(db: Session, count: int = 50):
    """Seed promotions."""
    print(f"Seeding {count} promotions...")
    promotions = []
    
    for i in range(count):
        start_date = fake.date_time_between(start_date="-1y", end_date="now")
        end_date = start_date + timedelta(days=random.randint(7, 90))
        
        promotion = Promotion(
            code=fake.unique.bothify(text="PROMO###??").upper(),
            description=fake.sentence(),
            discount_type=random.choice(["percentage", "fixed_amount"]),
            discount_value=Decimal(str(random.choice([5, 10, 15, 20, 25]))),
            max_discount=Decimal(str(random.choice([10, 20, 50]))),
            min_trip_amount=Decimal(str(random.choice([10, 20, 30]))),
            start_date=start_date,
            end_date=end_date,
            is_active=start_date <= datetime.now() <= end_date,
            usage_count=random.randint(0, 500)
        )
        promotions.append(promotion)
    
    db.bulk_save_objects(promotions)
    db.commit()
    print(f"Created {count} promotions")
    return promotions


def seed_payments(db: Session, count: int = 1000):
    """Seed payments."""
    print(f"Seeding {count} payments...")
    payments = []
    
    payment_methods = ["credit_card", "debit_card", "cash", "wallet"]
    statuses = ["completed", "completed", "completed", "pending", "failed"]
    
    for i in range(count):
        payment = Payment(
            amount=Decimal(str(round(random.uniform(5, 100), 2))),
            payment_method=random.choice(payment_methods),
            status=random.choice(statuses),
            transaction_id=fake.unique.uuid4(),
            created_at=fake.date_time_between(start_date="-1y", end_date="now")
        )
        payments.append(payment)
    
    db.bulk_save_objects(payments)
    db.commit()
    print(f"Created {count} payments")
    return payments


def seed_trips(db: Session, users: list, drivers: list, vehicles: list, regions: list, 
               payments: list, promotions: list, count: int = 1000):
    """Seed trips."""
    print(f"Seeding {count} trips...")
    trips = []
    
    statuses = ["completed", "completed", "completed", "cancelled"]
    
    for i in range(count):
        pickup_time = fake.date_time_between(start_date="-1y", end_date="now")
        duration = random.randint(5, 90)
        dropoff_time = pickup_time + timedelta(minutes=duration)
        distance = round(random.uniform(1, 50), 2)
        base_fare = Decimal(str(round(5 + distance * 1.5, 2)))
        surge_multiplier = random.choice([1.0, 1.0, 1.0, 1.2, 1.5, 2.0])
        total_fare = base_fare * Decimal(str(surge_multiplier))
        
        trip = Trip(
            user_id=random.choice(users).id,
            driver_id=random.choice(drivers).id,
            vehicle_id=random.choice(vehicles).id,
            region_id=random.choice(regions).id,
            pickup_location=fake.address().replace('\n', ', ')[:255],
            dropoff_location=fake.address().replace('\n', ', ')[:255],
            pickup_time=pickup_time,
            dropoff_time=dropoff_time,
            distance_km=distance,
            duration_minutes=duration,
            base_fare=base_fare,
            surge_multiplier=surge_multiplier,
            total_fare=total_fare,
            status=random.choice(statuses),
            payment_id=payments[i].id if i < len(payments) else None,
            promotion_id=random.choice(promotions).id if random.random() < 0.2 else None
        )
        trips.append(trip)
    
    db.bulk_save_objects(trips)
    db.commit()
    print(f"Created {count} trips")
    return trips


def seed_ratings(db: Session, trips: list, count: int = 800):
    """Seed ratings (not all trips have ratings)."""
    print(f"Seeding {count} ratings...")
    ratings = []
    
    # Select random trips
    rated_trips = random.sample(trips, min(count, len(trips)))
    
    for trip in rated_trips:
        rating = Rating(
            trip_id=trip.id,
            user_id=trip.user_id,
            driver_id=trip.driver_id,
            user_rating=random.randint(3, 5),
            driver_rating=random.randint(3, 5),
            user_comment=fake.sentence() if random.random() < 0.3 else None,
            driver_comment=fake.sentence() if random.random() < 0.2 else None,
            created_at=trip.dropoff_time + timedelta(minutes=random.randint(5, 120))
        )
        ratings.append(rating)
    
    db.bulk_save_objects(ratings)
    db.commit()
    print(f"Created {len(ratings)} ratings")
    return ratings


def seed_surge_pricing(db: Session, regions: list, count: int = 200):
    """Seed surge pricing events."""
    print(f"Seeding {count} surge pricing events...")
    surges = []
    
    reasons = ["high_demand", "event", "weather", "rush_hour", "concert", "sports_event"]
    
    for i in range(count):
        start_time = fake.date_time_between(start_date="-6m", end_date="now")
        duration = random.randint(30, 180)
        
        surge = SurgePricing(
            region_id=random.choice(regions).id,
            area=fake.city(),
            surge_multiplier=round(random.uniform(1.2, 3.0), 1),
            start_time=start_time,
            end_time=start_time + timedelta(minutes=duration),
            reason=random.choice(reasons),
            is_active=False  # Historical data
        )
        surges.append(surge)
    
    db.bulk_save_objects(surges)
    db.commit()
    print(f"Created {count} surge pricing events")
    return surges


def seed_support_tickets(db: Session, users: list, trips: list, count: int = 300):
    """Seed support tickets."""
    print(f"Seeding {count} support tickets...")
    tickets = []
    
    categories = ["payment", "driver", "safety", "trip_issue", "app", "other"]
    statuses = ["open", "in_progress", "resolved", "closed"]
    priorities = ["low", "medium", "high", "urgent"]
    
    for i in range(count):
        created = fake.date_time_between(start_date="-6m", end_date="now")
        status = random.choice(statuses)
        
        ticket = SupportTicket(
            user_id=random.choice(users).id,
            trip_id=random.choice(trips).id if random.random() < 0.7 else None,
            subject=fake.sentence()[:255],
            description=fake.paragraph(),
            category=random.choice(categories),
            status=status,
            priority=random.choice(priorities),
            created_at=created,
            updated_at=created + timedelta(hours=random.randint(1, 48)),
            resolved_at=created + timedelta(days=random.randint(1, 7)) if status in ["resolved", "closed"] else None
        )
        tickets.append(ticket)
    
    db.bulk_save_objects(tickets)
    db.commit()
    print(f"Created {count} support tickets")
    return tickets


def seed_flattened_tables(db: Session, regions: list):
    """Seed flattened analytics tables."""
    print("Seeding flattened analytics tables...")
    
    # Trip metrics daily
    metrics = []
    start_date = datetime.now() - timedelta(days=90)
    
    for day in range(90):
        current_date = (start_date + timedelta(days=day)).date()
        
        for region in regions:
            metric = TripMetricsDaily(
                date=current_date,
                region_id=region.id,
                total_trips=random.randint(100, 500),
                completed_trips=random.randint(80, 450),
                cancelled_trips=random.randint(5, 50),
                total_revenue=Decimal(str(round(random.uniform(5000, 25000), 2))),
                avg_trip_distance=round(random.uniform(5, 20), 2),
                avg_trip_duration=round(random.uniform(15, 45), 2),
                avg_fare=Decimal(str(round(random.uniform(15, 40), 2))),
                unique_users=random.randint(50, 300),
                unique_drivers=random.randint(30, 150),
                surge_trips=random.randint(10, 100),
                promo_trips=random.randint(20, 150)
            )
            metrics.append(metric)
    
    db.bulk_save_objects(metrics)
    db.commit()
    print(f"Created {len(metrics)} trip metrics daily records")
    
    # Region revenue summary
    summaries = []
    for year in [2024, 2025, 2026]:
        for month in range(1, 13):
            if year == 2026 and month > 2:  # Current is Feb 2026
                break
                
            for region in regions:
                summary = RegionRevenueSummary(
                    region_id=region.id,
                    year=year,
                    month=month,
                    total_revenue=Decimal(str(round(random.uniform(100000, 500000), 2))),
                    total_trips=random.randint(2000, 10000),
                    total_distance_km=round(random.uniform(20000, 100000), 2),
                    active_users=random.randint(500, 2000),
                    active_drivers=random.randint(200, 800),
                    avg_rating=round(random.uniform(4.0, 4.9), 2),
                    support_tickets=random.randint(50, 300)
                )
                summaries.append(summary)
    
    db.bulk_save_objects(summaries)
    db.commit()
    print(f"Created {len(summaries)} region revenue summary records")


def seed_golden_queries(db: Session):
    """Seed golden queries for validation."""
    print("Seeding golden queries...")
    
    golden_queries = [
        {
            "question": "What is the total revenue for US and Canada region last month?",
            "sql_query": """
                SELECT SUM(total_revenue) as revenue 
                FROM region_revenue_summary rrs
                JOIN regions r ON rrs.region_id = r.id
                WHERE r.code = 'USNC' 
                AND rrs.year = 2026 AND rrs.month = 1
            """,
            "description": "Total revenue for USNC region in January 2026",
            "category": "revenue"
        },
        {
            "question": "How many trips were completed yesterday?",
            "sql_query": """
                SELECT SUM(completed_trips) as total
                FROM trip_metrics_daily
                WHERE date = CURRENT_DATE - INTERVAL '1 day'
            """,
            "description": "Total completed trips yesterday",
            "category": "trips"
        },
        {
            "question": "What is the average rating of drivers in APAC region?",
            "sql_query": """
                SELECT AVG(rating) as avg_rating
                FROM drivers d
                JOIN regions r ON d.region_id = r.id
                WHERE r.code = 'APAC' AND d.is_active = true
            """,
            "description": "Average driver rating in Asia Pacific",
            "category": "ratings"
        },
        {
            "question": "Top 5 drivers by total earnings?",
            "sql_query": """
                SELECT name, total_earnings
                FROM drivers
                WHERE is_active = true
                ORDER BY total_earnings DESC
                LIMIT 5
            """,
            "description": "Top earning active drivers",
            "category": "drivers"
        }
    ]
    
    for gq_data in golden_queries:
        gq = GoldenQuery(**gq_data, is_active=True)
        db.add(gq)
    
    db.commit()
    print(f"Created {len(golden_queries)} golden queries")


def seed_metadata(db: Session):
    """Seed metadata index."""
    print("Seeding metadata index...")
    
    metadata_entries = [
        # Regions
        {"table_name": "regions", "column_name": "code", "display_name": "Region Code",
         "description": "Unique code for geographic region", 
         "business_term": "USNC=US and Canada, EU=Europe, APAC=Asia Pacific, LATAM=Latin America"},
        
        # Trip metrics
        {"table_name": "trip_metrics_daily", "column_name": "total_revenue", 
         "display_name": "Daily Revenue", "description": "Total revenue for the day",
         "is_metric": True, "metric_definition": "SUM of all trip fares"},
        
        {"table_name": "trip_metrics_daily", "column_name": "completed_trips",
         "display_name": "Completed Trips", "description": "Number of successfully completed trips",
         "is_metric": True, "metric_definition": "COUNT of trips with status='completed'"},
        
        # Region revenue
        {"table_name": "region_revenue_summary", "column_name": "total_revenue",
         "display_name": "Monthly Revenue", "description": "Total monthly revenue by region",
         "is_metric": True, "metric_definition": "SUM of all trip fares in the month"},
        
        {"table_name": "region_revenue_summary", "column_name": "active_users",
         "display_name": "Active Users", "description": "Number of users who took at least one trip",
         "is_metric": True, "metric_definition": "COUNT DISTINCT users with trips in period"},
        
        # Trips
        {"table_name": "trips", "column_name": "total_fare", "display_name": "Trip Fare",
         "description": "Total fare charged for the trip including surge",
         "data_type": "numeric"},
        
        {"table_name": "trips", "column_name": "surge_multiplier", "display_name": "Surge Multiplier",
         "description": "Multiplier applied during high demand (1.0 = no surge)",
         "data_type": "float"},
    ]
    
    for entry in metadata_entries:
        metadata = MetadataIndex(**entry)
        db.add(metadata)
    
    db.commit()
    print(f"Created {len(metadata_entries)} metadata entries")


def main():
    """Main seeding function."""
    print("=" * 60)
    print("FINCH AI - Database Seeding Script")
    print("=" * 60)
    
    # Initialize database
    print("\nInitializing database schema...")
    init_db_sync()
    print("Database schema created successfully!")
    
    # Create session
    db = SyncSessionLocal()
    
    try:
        # Seed in order (respecting foreign keys)
        regions = seed_regions(db)
        users = [User(id=i+1, email=f"user{i}@example.com", name=f"User {i}") 
                for i in range(1000)]
        db.bulk_save_objects(users)
        db.commit()
        users = db.query(User).all()
        
        vehicles = seed_vehicles(db)
        vehicles_list = db.query(Vehicle).all()
        
        drivers = seed_drivers(db, regions, vehicles_list)
        drivers_list = db.query(Driver).all()
        
        promotions = seed_promotions(db)
        promotions_list = db.query(Promotion).all()
        
        payments = seed_payments(db)
        payments_list = db.query(Payment).all()
        
        trips = seed_trips(db, users, drivers_list, vehicles_list, regions, 
                          payments_list, promotions_list)
        trips_list = db.query(Trip).all()
        
        seed_ratings(db, trips_list)
        seed_surge_pricing(db, regions)
        seed_support_tickets(db, users, trips_list)
        
        # Seed flattened tables
        seed_flattened_tables(db, regions)
        
        # Seed system tables
        seed_golden_queries(db)
        seed_metadata(db)
        
        print("\n" + "=" * 60)
        print("✅ SEEDING COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print(f"\nDatabase Summary:")
        print(f"  - Users: {db.query(User).count()}")
        print(f"  - Drivers: {db.query(Driver).count()}")
        print(f"  - Vehicles: {db.query(Vehicle).count()}")
        print(f"  - Regions: {db.query(Region).count()}")
        print(f"  - Trips: {db.query(Trip).count()}")
        print(f"  - Payments: {db.query(Payment).count()}")
        print(f"  - Promotions: {db.query(Promotion).count()}")
        print(f"  - Ratings: {db.query(Rating).count()}")
        print(f"  - Support Tickets: {db.query(SupportTicket).count()}")
        print(f"  - Trip Metrics Daily: {db.query(TripMetricsDaily).count()}")
        print(f"  - Region Revenue Summary: {db.query(RegionRevenueSummary).count()}")
        print(f"  - Golden Queries: {db.query(GoldenQuery).count()}")
        print(f"  - Metadata Entries: {db.query(MetadataIndex).count()}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during seeding: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
