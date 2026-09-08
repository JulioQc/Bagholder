// The Bagholder model for Android: a plain Kotlin library the app depends on,
// a port of model.py. Its test runs fixtures/cases, the same files the Python
// and Swift tests run.
plugins {
    kotlin("jvm") version "2.0.21"
}

dependencies {
    testImplementation(kotlin("test"))
    testImplementation("org.json:json:20240303")
}

tasks.test {
    useJUnitPlatform()
    // the shared cases live outside the module: a regenerated case must rerun this
    inputs.dir("../../fixtures/cases")
    testLogging {
        events("failed")
        exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL
    }
}
