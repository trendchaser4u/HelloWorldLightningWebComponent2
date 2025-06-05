import { createElement } from "@lwc/engine-dom";
import HelloWorld from "c/helloWorld";
import getGreeting from "@salesforce/apex/HelloWorldController.getGreeting";
import getCurrentDateTime from "@salesforce/apex/HelloWorldController.getCurrentDateTime";

// Mock the Apex methods
jest.mock(
  "@salesforce/apex/HelloWorldController.getGreeting",
  () => {
    return {
      default: jest.fn()
    };
  },
  { virtual: true }
);

jest.mock(
  "@salesforce/apex/HelloWorldController.getCurrentDateTime",
  () => {
    return {
      default: jest.fn()
    };
  },
  { virtual: true }
);

describe("c-hello-world", () => {
  afterEach(() => {
    // The jsdom instance is shared across test cases in a single file so reset the DOM
    while (document.body.firstChild) {
      document.body.removeChild(document.body.firstChild);
    }
    // Clear all mocks
    jest.clearAllMocks();
  });

  it("displays default greeting on component load", async () => {
    // Arrange
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });

    // Act
    document.body.appendChild(element);

    // Wait for connectedCallback to complete
    await Promise.resolve();

    // Assert
    const greetingElement = element.shadowRoot.querySelector(
      ".slds-text-heading_medium"
    );
    expect(greetingElement).not.toBeNull();
    expect(greetingElement.textContent).toBe("Hello, World!");
    expect(getCurrentDateTime).toHaveBeenCalled();
  });

  it("displays current date/time on component load", async () => {
    // Arrange
    const mockDateTime = "Monday, June 04, 2025 at 10:30 AM";
    getCurrentDateTime.mockResolvedValue(mockDateTime);

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });

    // Act
    document.body.appendChild(element);
    // Wait for connectedCallback and async operations to complete
    await Promise.resolve();
    await Promise.resolve();

    // Assert
    const dateTimeElement =
      element.shadowRoot.querySelector(".current-date-time");
    expect(dateTimeElement).not.toBeNull();
    expect(dateTimeElement.textContent).toBe(mockDateTime);
  });

  it("calls apex method when get greeting button is clicked", async () => {
    // Arrange
    getGreeting.mockResolvedValue("Hello, Salesforce!");
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });
    document.body.appendChild(element);
    await Promise.resolve();

    // Act
    const inputElement = element.shadowRoot.querySelector("lightning-input");
    inputElement.value = "Salesforce";
    inputElement.dispatchEvent(new CustomEvent("change"));

    const buttonElement = element.shadowRoot.querySelector("lightning-button");
    buttonElement.click();

    // Wait for async operations to complete
    await Promise.resolve();
    await Promise.resolve();

    // Assert
    expect(getGreeting).toHaveBeenCalledWith({ name: "Salesforce" });
    const greetingElement = element.shadowRoot.querySelector(
      ".slds-text-heading_medium"
    );
    expect(greetingElement.textContent).toBe("Hello, Salesforce!");
  });

  it("handles empty input and calls apex method", async () => {
    // Arrange
    getGreeting.mockResolvedValue("Hello, World!");
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });
    document.body.appendChild(element);
    await Promise.resolve();

    // Act
    const inputElement = element.shadowRoot.querySelector("lightning-input");
    inputElement.value = "";
    inputElement.dispatchEvent(new CustomEvent("change"));

    const buttonElement = element.shadowRoot.querySelector("lightning-button");
    buttonElement.click();

    await Promise.resolve();

    // Assert
    expect(getGreeting).toHaveBeenCalledWith({ name: "" });
    const greetingElement = element.shadowRoot.querySelector(
      ".slds-text-heading_medium"
    );
    expect(greetingElement.textContent).toBe("Hello, World!");
  });

  it("displays error message when apex method fails", async () => {
    // Arrange
    const errorMessage = "Something went wrong";
    getGreeting.mockRejectedValue({ body: { message: errorMessage } });
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });
    document.body.appendChild(element);
    await Promise.resolve();
    await Promise.resolve();

    // Act
    const buttonElement = element.shadowRoot.querySelector("lightning-button");
    buttonElement.click();

    await Promise.resolve();
    await Promise.resolve();

    // Assert
    const greetingElement = element.shadowRoot.querySelector(
      ".slds-text-heading_medium"
    );
    expect(greetingElement.textContent).toBe(`Error: ${errorMessage}`);
  });

  it("displays the correct card title", () => {
    // Arrange
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });

    // Act
    document.body.appendChild(element);

    // Assert
    const cardElement = element.shadowRoot.querySelector("lightning-card");
    expect(cardElement).not.toBeNull();
    expect(cardElement.title).toBe("Hello World LWC");
  });

  it("displays the input with correct label", () => {
    // Arrange
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });

    // Act
    document.body.appendChild(element);

    // Assert
    const labelElement = element.shadowRoot.querySelector(
      ".slds-form-element__label"
    );
    expect(labelElement).not.toBeNull();
    expect(labelElement.textContent).toBe("Enter your name:");

    const inputElement = element.shadowRoot.querySelector("lightning-input");
    expect(inputElement).not.toBeNull();
    expect(inputElement.placeholder).toBe("Enter your name");
  });

  it("updates userName property when input value changes", () => {
    // Arrange
    getCurrentDateTime.mockResolvedValue("Monday, June 04, 2025 at 10:30 AM");

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });
    document.body.appendChild(element);

    // Act
    const inputElement = element.shadowRoot.querySelector("lightning-input");
    inputElement.value = "Trailblazer";
    inputElement.dispatchEvent(new CustomEvent("change"));

    // Assert
    expect(inputElement.value).toBe("Trailblazer");
  });

  it("handles getCurrentDateTime error gracefully", async () => {
    // Arrange
    getCurrentDateTime.mockRejectedValue(new Error("Network error"));

    const element = createElement("c-hello-world", {
      is: HelloWorld
    });

    // Act
    document.body.appendChild(element);
    await Promise.resolve();
    await Promise.resolve();

    // Assert
    const dateTimeElement = element.shadowRoot.querySelector(
      ".slds-text-body_small"
    );
    expect(dateTimeElement.textContent).toContain("Error loading date/time");
  });
});
