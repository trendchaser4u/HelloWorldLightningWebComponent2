@isTest
public class HelloWorldControllerTest {
  @isTest
  static void testGetGreetingWithName() {
    String result = HelloWorldController.getGreeting('Salesforce');
    Assert.areEqual(
      'Hello, Salesforce!',
      result,
      'Greeting with name should be formatted correctly'
    );
  }

  @isTest
  static void testGetGreetingWithoutName() {
    String result = HelloWorldController.getGreeting('');
    Assert.areEqual(
      'Hello, World!',
      result,
      'Greeting without name should return default message'
    );
  }

  @isTest
  static void testGetGreetingWithNull() {
    String result = HelloWorldController.getGreeting(null);
    Assert.areEqual(
      'Hello, World!',
      result,
      'Greeting with null should return default message'
    );
  }

  @isTest
  static void testGetCurrentDateTime() {
    String result = HelloWorldController.getCurrentDateTime();
    Assert.isTrue(
      result.contains('at'),
      'DateTime should contain "at" keyword'
    );
    Assert.isNotNull(result, 'DateTime should not be null');
  }
}
